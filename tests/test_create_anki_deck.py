import os
import subprocess
import sys

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
        lambda pdf_path: decker.ProcessingResult(
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
