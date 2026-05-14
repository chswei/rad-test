import os
import subprocess
import sys

from rich.console import Console

import create_anki_deck as decker


def test_stable_anki_id_does_not_depend_on_python_hash_seed():
    code = (
        "import create_anki_deck as decker; "
        "print(decker.stable_anki_id('example deck')); "
        "print(decker.stable_anki_id('example deck', 'model'))"
    )
    outputs = []

    for seed in ("1", "2"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.getcwd(),
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        outputs.append(result.stdout)

    assert outputs[0] == outputs[1]


def test_build_card_report_flags_missing_pairs_and_card_count():
    report = decker.build_card_report(
        question_images={"01": "q01.png", "02": "q02.png"},
        answer_images={"02": "a02.png", "03": "a03.png"},
        expected_cards=2,
    )

    assert report.num_cards == 1
    assert report.missing_answers == ["01"]
    assert report.missing_questions == ["03"]
    assert report.wrong_card_count is True
    assert report.success is False


def test_anki_card_back_shows_question_and_answer_images():
    model = decker.build_anki_model("example deck")
    template = model.templates[0]

    assert template["qfmt"] == "{{QuestionImage}}"
    assert "{{QuestionImage}}" in template["afmt"]
    assert "{{AnswerImage}}" in template["afmt"]
    assert template["afmt"].index("{{QuestionImage}}") < template["afmt"].index("{{AnswerImage}}")


def test_extract_images_closes_source_images_after_merging(tmp_path, monkeypatch):
    class FakeRect:
        width = 100
        height = 100
        y0 = 0

    class FakePixmap:
        def save(self, path):
            pass

    class FakePage:
        def get_pixmap(self, dpi, clip):
            return FakePixmap()

    class FakeDoc:
        def __getitem__(self, page_index):
            return FakePage()

    class FakeImage:
        size = (10, 10)

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeMergedImage:
        def paste(self, image, position):
            pass

        def save(self, path):
            pass

    opened_images = []

    def fake_open(path):
        image = FakeImage()
        opened_images.append(image)
        return image

    monkeypatch.setattr(decker.Image, "open", fake_open)
    monkeypatch.setattr(decker.Image, "new", lambda *args: FakeMergedImage())

    decker.extract_images(
        FakeDoc(),
        {"01": [(0, FakeRect()), (1, FakeRect())]},
        "Q",
        str(tmp_path),
        "deck",
    )

    assert opened_images
    assert all(image.closed for image in opened_images)


def test_main_returns_failure_when_any_pdf_processing_fails(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    (input_dir / "broken.pdf").write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(decker, "INPUT_DIR", str(input_dir))
    monkeypatch.setattr(decker, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(
        decker,
        "process_pdf",
        lambda pdf_path, progress=None, task_id=None, step_task_ids=None, overall_task_id=None, progress_label=None, output_console=None: decker.ProcessingResult(
            deck_name="broken",
            output_file=str(output_dir / "broken.apkg"),
            num_cards=0,
            report=decker.CardReport(
                num_cards=0,
                missing_answers=["01"],
                missing_questions=[],
                wrong_card_count=True,
            ),
            success=False,
        ),
    )

    assert decker.main() == 1


def test_main_renders_summary_table_for_processed_pdfs(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    (input_dir / "alpha.pdf").write_bytes(b"%PDF-1.4\n")
    (input_dir / "beta.pdf").write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(decker, "INPUT_DIR", str(input_dir))
    monkeypatch.setattr(decker, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(
        decker,
        "process_pdf",
        lambda pdf_path, progress=None, task_id=None, step_task_ids=None, overall_task_id=None, progress_label=None, output_console=None: decker.ProcessingResult(
            deck_name=os.path.splitext(os.path.basename(pdf_path))[0],
            output_file=str(output_dir / f"{os.path.splitext(os.path.basename(pdf_path))[0]}.apkg"),
            num_cards=50,
            report=decker.CardReport(
                num_cards=50,
                missing_answers=[],
                missing_questions=[],
                wrong_card_count=False,
            ),
            success=True,
        ),
    )

    console = Console(record=True, force_terminal=True, width=120)

    assert decker.main(console=console) == 0

    output = console.export_text()
    assert "全國聯合考 PDF 轉 Anki 卡片" in output
    assert "處理結果" in output
    assert "alpha" in output
    assert "beta" in output
    assert "50" in output
    assert "成功" in output


def test_process_pdf_renders_four_step_progress_rows(tmp_path, monkeypatch):
    class FakeDoc:
        def close(self):
            pass

    questions = {f"{num:02d}": f"q{num:02d}.png" for num in range(1, 51)}
    answers = {f"{num:02d}": f"a{num:02d}.png" for num in range(1, 51)}

    monkeypatch.setattr(decker, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(decker.fitz, "open", lambda pdf_path: FakeDoc())
    monkeypatch.setattr(decker, "find_markers_and_regions", lambda doc: (questions, answers))
    monkeypatch.setattr(
        decker,
        "extract_images",
        lambda doc, regions, prefix, temp_dir, deck_name: (
            {num: f"{deck_name}_{prefix}{num}.png" for num in regions},
            [str(tmp_path / f"{deck_name}_{prefix}{num}.png") for num in regions],
        ),
    )
    monkeypatch.setattr(decker, "create_anki_deck", lambda *args: 50)

    console = Console(record=True, force_terminal=True, width=120)

    with decker.build_progress(console) as progress:
        step_tasks = decker.add_pdf_step_tasks(progress)
        result = decker.process_pdf(
            str(tmp_path / "sample.pdf"),
            progress=progress,
            step_task_ids=step_tasks,
            output_console=console,
        )

    output = console.export_text()
    assert result.success is True
    assert "- sample | 步驟 1/4: 定位問題與答案區域" in output
    assert "步驟 1/4: 定位問題與答案區域" in output
    assert "找到 50 個問題和 50 個答案" in output
    assert "步驟 2/4: 擷取問題圖片" in output
    assert "成功處理 50 張問題圖片" in output
    assert "步驟 3/4: 擷取答案圖片" in output
    assert "成功處理 50 張答案圖片" in output
    assert "步驟 4/4: 產生 Anki 卡片" in output
    assert "成功建立 50 張卡片" in output
    assert "sample | 完成 50 張卡片" not in output
    assert "完成 步驟 1/4" not in output


def test_summary_table_title_is_left_aligned():
    console = Console(record=True, force_terminal=True, width=80)
    report = decker.CardReport(
        num_cards=50,
        missing_answers=[],
        missing_questions=[],
        wrong_card_count=False,
    )
    result = decker.ProcessingResult(
        deck_name="sample",
        output_file="output/sample.apkg",
        num_cards=50,
        report=report,
        success=True,
    )

    decker.render_summary_table([result], console)

    output = console.export_text()
    title_line = next(line for line in output.splitlines() if "處理結果" in line)
    assert title_line.startswith("處理結果")


def test_process_pdf_advances_overall_progress_by_step(tmp_path, monkeypatch):
    class FakeDoc:
        def close(self):
            pass

    questions = {f"{num:02d}": f"q{num:02d}.png" for num in range(1, 51)}
    answers = {f"{num:02d}": f"a{num:02d}.png" for num in range(1, 51)}

    monkeypatch.setattr(decker, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(decker.fitz, "open", lambda pdf_path: FakeDoc())
    monkeypatch.setattr(decker, "find_markers_and_regions", lambda doc: (questions, answers))
    monkeypatch.setattr(
        decker,
        "extract_images",
        lambda doc, regions, prefix, temp_dir, deck_name: (
            {num: f"{deck_name}_{prefix}{num}.png" for num in regions},
            [str(tmp_path / f"{deck_name}_{prefix}{num}.png") for num in regions],
        ),
    )
    monkeypatch.setattr(decker, "create_anki_deck", lambda *args: 50)

    console = Console(record=True, force_terminal=True, width=120)

    with decker.build_progress(console) as progress:
        overall_task = progress.add_task("整體進度", total=len(decker.PDF_STEPS))
        step_tasks = decker.add_pdf_step_tasks(progress)
        decker.process_pdf(
            str(tmp_path / "sample.pdf"),
            progress=progress,
            step_task_ids=step_tasks,
            overall_task_id=overall_task,
            output_console=console,
        )

        overall = progress.tasks[0]
        assert overall.completed == len(decker.PDF_STEPS)
        assert overall.total == len(decker.PDF_STEPS)


def test_progress_keeps_completed_step_rows_for_multiple_pdfs(tmp_path, monkeypatch):
    class FakeDoc:
        def close(self):
            pass

    questions = {f"{num:02d}": f"q{num:02d}.png" for num in range(1, 51)}
    answers = {f"{num:02d}": f"a{num:02d}.png" for num in range(1, 51)}

    monkeypatch.setattr(decker, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(decker.fitz, "open", lambda pdf_path: FakeDoc())
    monkeypatch.setattr(decker, "find_markers_and_regions", lambda doc: (questions, answers))
    monkeypatch.setattr(
        decker,
        "extract_images",
        lambda doc, regions, prefix, temp_dir, deck_name: (
            {num: f"{deck_name}_{prefix}{num}.png" for num in regions},
            [str(tmp_path / f"{deck_name}_{prefix}{num}.png") for num in regions],
        ),
    )
    monkeypatch.setattr(decker, "create_anki_deck", lambda *args: 50)

    console = Console(record=True, force_terminal=True, width=160)

    with decker.build_progress(console) as progress:
        overall_task = progress.add_task("整體進度", total=2 * len(decker.PDF_STEPS))

        alpha_steps = decker.add_pdf_step_tasks(progress, "alpha")
        decker.process_pdf(
            str(tmp_path / "alpha.pdf"),
            progress=progress,
            step_task_ids=alpha_steps,
            overall_task_id=overall_task,
            output_console=console,
        )

        beta_steps = decker.add_pdf_step_tasks(progress, "beta")
        decker.process_pdf(
            str(tmp_path / "beta.pdf"),
            progress=progress,
            step_task_ids=beta_steps,
            overall_task_id=overall_task,
            output_console=console,
        )

    output = console.export_text()
    assert "alpha | 步驟 1/4: 定位問題與答案區域" in output
    assert "alpha | 步驟 4/4: 產生 Anki 卡片" in output
    assert "beta | 步驟 1/4: 定位問題與答案區域" in output
    assert "beta | 步驟 4/4: 產生 Anki 卡片" in output


def test_process_pdf_can_use_short_progress_label(tmp_path, monkeypatch):
    class FakeDoc:
        def close(self):
            pass

    questions = {f"{num:02d}": f"q{num:02d}.png" for num in range(1, 51)}
    answers = {f"{num:02d}": f"a{num:02d}.png" for num in range(1, 51)}

    monkeypatch.setattr(decker, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(decker.fitz, "open", lambda pdf_path: FakeDoc())
    monkeypatch.setattr(decker, "find_markers_and_regions", lambda doc: (questions, answers))
    monkeypatch.setattr(
        decker,
        "extract_images",
        lambda doc, regions, prefix, temp_dir, deck_name: (
            {num: f"{deck_name}_{prefix}{num}.png" for num in regions},
            [str(tmp_path / f"{deck_name}_{prefix}{num}.png") for num in regions],
        ),
    )
    monkeypatch.setattr(decker, "create_anki_deck", lambda *args: 50)

    console = Console(record=True, force_terminal=True, width=160)

    with decker.build_progress(console) as progress:
        step_tasks = decker.add_pdf_step_tasks(progress, "檔案 1/2")
        decker.process_pdf(
            str(tmp_path / "very_long_pdf_name.pdf"),
            progress=progress,
            step_task_ids=step_tasks,
            progress_label="檔案 1/2",
            output_console=console,
        )

    output = console.export_text()
    assert "檔案 1/2 | 步驟 1/4: 定位問題與答案區域" in output
    assert "檔案 1/2 | 步驟 4/4: 產生 Anki 卡片" in output
    assert "very_long_pdf_name | 步驟" not in output
