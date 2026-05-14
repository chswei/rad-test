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

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

# --- 組態設定 ---
INPUT_DIR = "input"
OUTPUT_DIR = "output"
ANKI_MODEL_NAME_PREFIX = "放射科閱片圖對圖模型"
EXPECTED_CARDS = 50
IMAGE_DPI = 200
console = Console()

STEP_FIND_REGIONS = "find_regions"
STEP_QUESTION_IMAGES = "question_images"
STEP_ANSWER_IMAGES = "answer_images"
STEP_CREATE_DECK = "create_deck"
PDF_STEPS = [
    (STEP_FIND_REGIONS, "步驟 1/4: 定位問題與答案區域"),
    (STEP_QUESTION_IMAGES, "步驟 2/4: 擷取問題圖片"),
    (STEP_ANSWER_IMAGES, "步驟 3/4: 擷取答案圖片"),
    (STEP_CREATE_DECK, "步驟 4/4: 產生 Anki 卡片"),
]


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


def print_card_report(report, output_console=None):
    output_console = output_console or console
    if report.missing_answers:
        output_console.print(f"[bold red]缺少答案的題號:[/] {', '.join(report.missing_answers)}")
    if report.missing_questions:
        output_console.print(f"[bold red]缺少題目的答案編號:[/] {', '.join(report.missing_questions)}")
    if report.wrong_card_count:
        output_console.print(
            f"[bold yellow]警告:[/] 最終產生的卡片數量為 {report.num_cards}，"
            f"不等於預期的 {EXPECTED_CARDS} 張。請檢查原檔案格式。"
        )


def build_progress(console):
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


def format_step_label(step_label, deck_name=None):
    return f"{deck_name} | {step_label}" if deck_name else step_label


def add_pdf_step_tasks(progress, deck_name=None):
    return {
        step_key: progress.add_task(format_step_label(step_label, deck_name), total=1)
        for step_key, step_label in PDF_STEPS
    }


def reset_pdf_step_tasks(progress, step_task_ids, deck_name=None):
    for step_key, step_label in PDF_STEPS:
        progress.reset(
            step_task_ids[step_key],
            total=1,
            completed=0,
            description=format_step_label(step_label, deck_name),
        )


def update_overall_progress(progress, overall_task_id):
    if not progress or overall_task_id is None:
        return

    progress.advance(overall_task_id)
    task = next(task for task in progress.tasks if task.id == overall_task_id)
    progress.update(
        overall_task_id,
        description=f"整體進度 | 已完成 {int(task.completed)}/{int(task.total)}",
    )


def complete_pdf_step(progress, step_task_ids, step_key, detail, overall_task_id=None, deck_name=None):
    if not progress or not step_task_ids:
        return

    task_id = step_task_ids[step_key]
    step_label = next(label for key, label in PDF_STEPS if key == step_key)
    row_label = format_step_label(step_label, deck_name)
    progress.update(
        task_id,
        description=f"{row_label} | {detail}",
        completed=1,
    )
    update_overall_progress(progress, overall_task_id)


def render_summary_table(results, output_console):
    table = Table(title="處理結果", show_lines=True)
    table.add_column("PDF", style="cyan", overflow="fold")
    table.add_column("卡片數", justify="right")
    table.add_column("狀態", justify="center")

    for result in results:
        status = "[green]成功[/]" if result.success else "[red]需檢查[/]"
        table.add_row(
            result.deck_name,
            str(result.num_cards),
            status,
        )

    output_console.print(table)


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

def process_pdf(
    pdf_path,
    progress=None,
    task_id=None,
    step_task_ids=None,
    overall_task_id=None,
    progress_label=None,
    output_console=None,
):
    """處理單一PDF檔案的完整流程。"""
    output_console = output_console or console
    
    deck_name = os.path.basename(os.path.splitext(pdf_path)[0])
    step_label_prefix = progress_label or deck_name
    anki_output_file = os.path.join(OUTPUT_DIR, deck_name + ".apkg")
    
    temp_dir = os.path.join(OUTPUT_DIR, f"temp_images_for_{deck_name}")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    doc = None
    try:
        doc = fitz.open(pdf_path)
        
        if progress and task_id is not None:
            progress.update(task_id, description=f"{deck_name} | 定位問題與答案區域")
        q_regions, a_regions = find_markers_and_regions(doc)
        if progress and task_id is not None:
            progress.advance(task_id)
        complete_pdf_step(
            progress,
            step_task_ids,
            STEP_FIND_REGIONS,
            f"找到 {len(q_regions)} 個問題和 {len(a_regions)} 個答案。",
            overall_task_id,
            step_label_prefix,
        )

        if progress and task_id is not None:
            progress.update(task_id, description=f"{deck_name} | 擷取問題圖片")
        question_images, q_media = extract_images(doc, q_regions, "Q", temp_dir, deck_name)
        if progress and task_id is not None:
            progress.advance(task_id)
        complete_pdf_step(
            progress,
            step_task_ids,
            STEP_QUESTION_IMAGES,
            f"成功處理 {len(question_images)} 張問題圖片。",
            overall_task_id,
            step_label_prefix,
        )

        if progress and task_id is not None:
            progress.update(task_id, description=f"{deck_name} | 擷取答案圖片")
        answer_images, a_media = extract_images(doc, a_regions, "A", temp_dir, deck_name)
        if progress and task_id is not None:
            progress.advance(task_id)
        complete_pdf_step(
            progress,
            step_task_ids,
            STEP_ANSWER_IMAGES,
            f"成功處理 {len(answer_images)} 張答案圖片。",
            overall_task_id,
            step_label_prefix,
        )
        
        if progress and task_id is not None:
            progress.update(task_id, description=f"{deck_name} | 產生 Anki 卡片")
        all_media_files = q_media + a_media
        report = build_card_report(question_images, answer_images)
        num_cards = create_anki_deck(deck_name, anki_output_file, question_images, answer_images, all_media_files)
        if progress and task_id is not None:
            progress.advance(task_id)
            progress.update(
                task_id,
                description=f"{deck_name} | 完成 {num_cards} 張卡片",
            )
        complete_pdf_step(
            progress,
            step_task_ids,
            STEP_CREATE_DECK,
            f"成功建立 {num_cards} 張卡片。",
            overall_task_id,
            step_label_prefix,
        )

        return ProcessingResult(
            deck_name=deck_name,
            output_file=anki_output_file,
            num_cards=num_cards,
            report=report,
            success=report.success,
        )

    except Exception as e:
        if progress and task_id is not None:
            progress.update(task_id, description=f"{deck_name} | 處理失敗")
        output_console.print(f"[bold red]處理 '{pdf_path}' 時發生嚴重錯誤:[/] {e}")
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

def main(console=None):
    """主執行函數，負責遍歷資料夾並處理所有PDF。"""
    output_console = console or globals()["console"]
    output_console.print(Panel.fit("全國聯合考 PDF 轉 Anki 卡片", style="bold cyan"))
    
    if not os.path.exists(INPUT_DIR):
        os.makedirs(INPUT_DIR)
        output_console.print(f"\n[bold yellow]輸入資料夾 '{INPUT_DIR}' 已建立。[/]")
        output_console.print("請將要處理的 PDF 檔案放入該資料夾後，再重新執行一次。")
        return 1
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    pdf_files = sorted(glob.glob(os.path.join(INPUT_DIR, '*.pdf')))
    
    if not pdf_files:
        output_console.print(f"\n[bold yellow]在 '{INPUT_DIR}' 中沒有找到任何 PDF 檔案。[/]")
        return 1
        
    output_console.print(f"\n在 [bold]{INPUT_DIR}[/] 中找到 [bold cyan]{len(pdf_files)}[/] 個 PDF 檔案。")

    results = []
    with build_progress(output_console) as progress:
        total_steps = len(pdf_files) * len(PDF_STEPS)
        overall_task = progress.add_task(f"整體進度 | 已完成 0/{total_steps}", total=total_steps)
        for index, pdf_path in enumerate(pdf_files, start=1):
            deck_name = os.path.basename(os.path.splitext(pdf_path)[0])
            step_task_ids = add_pdf_step_tasks(progress, f"檔案 {index}/{len(pdf_files)}")
            progress.update(overall_task, description=f"整體進度 | 正在處理 {deck_name}")
            result = process_pdf(
                pdf_path,
                progress=progress,
                step_task_ids=step_task_ids,
                overall_task_id=overall_task,
                progress_label=f"檔案 {index}/{len(pdf_files)}",
                output_console=output_console,
            )
            results.append(result)
            if not result.report.success:
                progress.update(overall_task, description=f"整體進度 | {deck_name} 需檢查")

    output_console.print()
    render_summary_table(results, output_console)
    output_console.print(f"輸出資料夾: [bold]{OUTPUT_DIR}[/]")

    failed_results = [result for result in results if not result.success]
    for result in failed_results:
        output_console.print(f"\n[bold yellow]{result.deck_name} 需要檢查:[/]")
        print_card_report(result.report, output_console)

    output_console.print("\n[bold green]全部處理完畢[/]" if not failed_results else "\n[bold yellow]全部處理完畢，部分檔案需要檢查[/]")
    return 0 if all(result.success for result in results) else 1

if __name__ == "__main__":
    sys.exit(main())
