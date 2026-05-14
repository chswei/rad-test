import pymupdf as fitz
import genanki
from PIL import Image
from dataclasses import dataclass
import glob
import hashlib
import os
import re
import shutil
import sys

# --- 組態設定 ---
INPUT_DIR = "input"
OUTPUT_DIR = "output"
ANKI_MODEL_NAME_PREFIX = "放射科閱片圖對圖模型"
EXPECTED_CARDS = 50
IMAGE_DPI = 200


@dataclass
class CardReport:
    num_cards: int
    missing_answers: list[str]
    missing_questions: list[str]
    wrong_card_count: bool

    @property
    def success(self):
        return not self.missing_answers and not self.missing_questions and not self.wrong_card_count


@dataclass
class ProcessingResult:
    deck_name: str
    output_file: str
    num_cards: int
    report: CardReport
    success: bool


def stable_anki_id(value, namespace=""):
    """產生跨執行程序穩定的 Anki deck/model ID。"""
    digest = hashlib.sha256(f"rad-test:{namespace}:{value}".encode("utf-8")).hexdigest()
    stable_id = int(digest[:16], 16) % (10**10)
    return stable_id or 1


def build_card_report(question_images, answer_images, expected_cards=EXPECTED_CARDS):
    paired_nums = set(question_images) & set(answer_images)
    missing_answers = sorted(set(question_images) - set(answer_images))
    missing_questions = sorted(set(answer_images) - set(question_images))
    num_cards = len(paired_nums)
    wrong_card_count = expected_cards is not None and num_cards != expected_cards

    return CardReport(
        num_cards=num_cards,
        missing_answers=missing_answers,
        missing_questions=missing_questions,
        wrong_card_count=wrong_card_count,
    )


def print_card_report(report):
    if report.missing_answers:
        print(f"    > !!! 缺少答案的題號: {', '.join(report.missing_answers)}")
    if report.missing_questions:
        print(f"    > !!! 缺少題目的答案編號: {', '.join(report.missing_questions)}")
    if report.wrong_card_count:
        print(
            f"    > !!! 警告: 最終產生的卡片數量為 {report.num_cards}，"
            f"不等於預期的 {EXPECTED_CARDS} 張。請檢查原檔案格式。"
        )


def build_anki_model(deck_name):
    model_id = stable_anki_id(deck_name, "image_model_v8")
    return genanki.Model(
        model_id,
        f"{ANKI_MODEL_NAME_PREFIX} - {deck_name}",
        fields=[{'name': 'QuestionImage'}, {'name': 'AnswerImage'}],
        templates=[{
            'name': 'Card 1',
            'qfmt': "{{QuestionImage}}",
            'afmt': """
<div class="question">{{QuestionImage}}</div>
<hr>
<div class="answer">{{AnswerImage}}</div>
""",
        }],
        css="""
.card {
  margin: 0;
  padding: 0;
  text-align: center;
  background: #111;
}
img {
  display: block;
  margin: 0 auto;
  max-width: 100%;
  max-height: 96vh;
  height: auto;
}
.question img,
.answer img {
  max-height: 46vh;
}
hr {
  border: 0;
  border-top: 1px solid #444;
  margin: 12px 0;
}
""")


def find_markers_and_regions(doc):
    """
    解析PDF，找到Q/A標記，並計算每個標記對應的內容區域。
    返回一個字典，將題號映射到一個包含 (頁碼, 截圖區域) 的列表。
    """
    q_regions = {}
    a_regions = {}
    pattern_suffix = r"(?:-\d+|\s*\(\d+(?:\/\d+)?\))?"
    q_pattern = re.compile(r"^Q(\d{1,2})" + pattern_suffix + r"$", re.IGNORECASE)
    a_pattern = re.compile(r"^A(\d{1,2})" + pattern_suffix + r"$", re.IGNORECASE)
    # 特殊格式: 編號:xx
    a_special_pattern = re.compile(r"編號[:：](\d{1,2})", re.IGNORECASE)

    for i, page in enumerate(doc):
        # 優先處理特殊答案格式
        text = page.get_text("text")
        a_special_match = a_special_pattern.search(text)
        if a_special_match:
            num = a_special_match.group(1).zfill(2)
            if num not in a_regions:
                a_regions[num] = []
            a_regions[num].append((i, page.rect))
            continue

        # 標準格式處理
        words = page.get_text("words")
        markers = []
        for word in words:
            text = word[4]
            bbox = fitz.Rect(word[:4])
            q_match = q_pattern.match(text)
            a_match = a_pattern.match(text)
            
            if q_match:
                num = q_match.group(1).zfill(2)
                markers.append({'type': 'q', 'num': num, 'bbox': bbox})
            elif a_match:
                num = a_match.group(1).zfill(2)
                markers.append({'type': 'a', 'num': num, 'bbox': bbox})

        if not markers:
            continue

        markers.sort(key=lambda m: m['bbox'].y0)

        for j, marker in enumerate(markers):
            top = marker['bbox'].y0
            bottom = markers[j+1]['bbox'].y0 if j + 1 < len(markers) else page.rect.height
            crop_box = fitz.Rect(0, top, page.rect.width, bottom)
            
            target_dict = q_regions if marker['type'] == 'q' else a_regions
            if marker['num'] not in target_dict:
                target_dict[marker['num']] = []
            target_dict[marker['num']].append((i, crop_box))
            
    return q_regions, a_regions

def extract_images(doc, regions_dict, prefix, temp_dir, deck_name):
    """根據提供的區域列表，從PDF中精準截圖，並使用唯一檔名。"""
    image_map = {}
    media_paths = []

    for item_num, regions in sorted(regions_dict.items()):
        image_paths = []
        regions.sort(key=lambda r: (r[0], r[1].y0))
        
        for i, (page_index, crop_box) in enumerate(regions):
            if crop_box.height < 10 or crop_box.width < 10:
                continue
            page = doc[page_index]
            pix = page.get_pixmap(dpi=IMAGE_DPI, clip=crop_box)
            # --- 修正: 使用 deck_name 作為前綴，確保檔名唯一 ---
            temp_img_path = os.path.join(temp_dir, f"temp_{deck_name}_{prefix}{item_num}_{i}.png")
            pix.save(temp_img_path)
            image_paths.append(temp_img_path)

        if not image_paths:
            continue

        # --- 修正: 最終檔名也包含唯一前綴 ---
        final_image_filename = f"{deck_name}_{prefix}{item_num}.png"
        final_image_path = os.path.join(temp_dir, final_image_filename)

        if len(image_paths) > 1:
            images = [Image.open(p) for p in image_paths]
            widths, heights = zip(*(i.size for i in images))
            total_height = sum(heights)
            max_width = max(widths)
            merged_image = Image.new('RGB', (max_width, total_height), 'white')
            y_offset = 0
            for im in images:
                merged_image.paste(im, (0, y_offset))
                y_offset += im.size[1]
            merged_image.save(final_image_path)
        else:
            shutil.move(image_paths[0], final_image_path)

        image_map[item_num] = final_image_filename
        media_paths.append(final_image_path)

    return image_map, media_paths

def create_anki_deck(deck_name, anki_output_file, question_images, answer_images, all_media_files):
    """使用圖片正反面建立Anki .apkg檔案。"""
    deck_id = stable_anki_id(deck_name, "deck")
    my_model = build_anki_model(deck_name)
    my_deck = genanki.Deck(deck_id, deck_name)

    for q_num, q_filename in sorted(question_images.items()):
        if q_num in answer_images:
            a_filename = answer_images[q_num]
            # --- 修正: 移除 os.path.basename，因為檔名已經是乾淨的 ---
            front_content = f"<!-- {q_filename} -->\n<img src='{q_filename}'>"
            back_content = f"<img src='{a_filename}'>"
            my_note = genanki.Note(
                model=my_model,
                fields=[front_content, back_content],
                guid=genanki.guid_for(deck_name, q_num),
            )
            my_deck.add_note(my_note)

    my_package = genanki.Package(my_deck)
    my_package.media_files = all_media_files
    my_package.write_to_file(anki_output_file)
    
    return len(my_deck.notes)

def process_pdf(pdf_path):
    """處理單一PDF檔案的完整流程。"""
    print(f"\n--- 開始處理檔案: {os.path.basename(pdf_path)} ---")
    
    deck_name = os.path.basename(os.path.splitext(pdf_path)[0])
    anki_output_file = os.path.join(OUTPUT_DIR, deck_name + ".apkg")
    
    temp_dir = os.path.join(OUTPUT_DIR, f"temp_images_for_{deck_name}")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    doc = None
    try:
        doc = fitz.open(pdf_path)
        
        print("  - 步驟 1/4: 定位問題與答案區域...")
        q_regions, a_regions = find_markers_and_regions(doc)
        print(f"    > 找到 {len(q_regions)} 個問題和 {len(a_regions)} 個答案。")

        print("  - 步驟 2/4: 擷取問題圖片...")
        question_images, q_media = extract_images(doc, q_regions, "Q", temp_dir, deck_name)
        print(f"    > 成功處理 {len(question_images)} 張問題圖片。")

        print("  - 步驟 3/4: 擷取答案圖片...")
        answer_images, a_media = extract_images(doc, a_regions, "A", temp_dir, deck_name)
        print(f"    > 成功處理 {len(answer_images)} 張答案圖片。")
        
        print("  - 步驟 4/4: 產生 Anki 卡片...")
        all_media_files = q_media + a_media
        report = build_card_report(question_images, answer_images)
        num_cards = create_anki_deck(deck_name, anki_output_file, question_images, answer_images, all_media_files)
        print(f"    > 成功建立 {num_cards} 張卡片。")
        print_card_report(report)

        print(f"--- 完成！已產生 Anki 檔案 '{anki_output_file}' ---")
        return ProcessingResult(
            deck_name=deck_name,
            output_file=anki_output_file,
            num_cards=num_cards,
            report=report,
            success=report.success,
        )

    except Exception as e:
        print(f"處理 '{pdf_path}' 時發生嚴重錯誤: {e}")
        report = CardReport(
            num_cards=0,
            missing_answers=[],
            missing_questions=[],
            wrong_card_count=True,
        )
        return ProcessingResult(
            deck_name=deck_name,
            output_file=anki_output_file,
            num_cards=0,
            report=report,
            success=False,
        )
    finally:
        if doc:
            doc.close()
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def main():
    """主執行函數，負責遍歷資料夾並處理所有PDF。"""
    print("--- Anki 批次處理腳本 (穩定 ID 模式 v8) ---")
    
    if not os.path.exists(INPUT_DIR):
        os.makedirs(INPUT_DIR)
        print(f"\n輸入資料夾 '{INPUT_DIR}' 已建立。")
        print(f"請將要處理的 PDF 檔案放入該資料夾後，再重新執行一次。")
        return 1
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    pdf_files = sorted(glob.glob(os.path.join(INPUT_DIR, '*.pdf')))
    
    if not pdf_files:
        print(f"\n在 '{INPUT_DIR}' 中沒有找到任何 PDF 檔案。")
        return 1
        
    print(f"\n在 '{INPUT_DIR}' 中找到 {len(pdf_files)} 個 PDF 檔案，準備開始處理...")

    results = [process_pdf(pdf_path) for pdf_path in pdf_files]

    print(f"\n--- 全部處理完畢 ---")
    return 0 if all(result.success for result in results) else 1

if __name__ == "__main__":
    sys.exit(main())
