from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path
from html import escape

import gradio as gr
from agent import Receipt, extract_data_from_receipt

UPLOAD_DIR = Path("receipts")
UPLOAD_DIR.mkdir(exist_ok=True)

# While the upload area is locked, Gradio replaces the drop zone with an empty
# placeholder and the file <input> disappears. These rules grey that state out,
# keep it the same height as the drop zone and show a message instead of an icon.
CSS = """
#uploader:not(:has(input[type="file"])) {
    /* a grey tint derived from the text colour, so it works in light and dark mode */
    background: color-mix(in srgb, var(--body-text-color) 10%, transparent);
    cursor: not-allowed;
}
#uploader:not(:has(input[type="file"])) .empty {
    height: 140px;
    min-height: 140px;
}
#uploader:not(:has(input[type="file"])) .empty > * {
    display: none;
}
#uploader:not(:has(input[type="file"])) .empty::after {
    content: "Processing receipt… upload is locked";
    color: var(--body-text-color-subdued);
}
"""

SOURCE_LABELS = {
    "receipt": "Receipt",
    "web_search": "web search",
    "vectordb": "vector db",
    "not_found": "Not found",
}


# Helper functions
def save_upload(tmp_path: str) -> Path:
    """Copy Gradio's temp upload into UPLOAD_DIR under a unique, sortable name"""
    src = Path(tmp_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = src.suffix.lower()
    dest = UPLOAD_DIR / f"{stamp}_{uuid.uuid4().hex[:8]}{suffix}"
    shutil.copy2(src, dest)
    return dest


def cell(value: object) -> str:
    """Make a value safe for Markdown table cell"""
    if value is None or value == "":
        return "-"
    return escape(str(value))


def saved_note(path: str | Path) -> str:
    """The 'Saved as …' line shown under the result."""
    return f"<p>Saved as <code>{escape(str(path))}</code></p>"


def render_receipt(receipt: Receipt) -> str:
    """Render the receipt as a Markdown table"""
    shop_src = SOURCE_LABELS.get(receipt.shop_source, receipt.shop_source)
    cvr_src = SOURCE_LABELS.get(receipt.cvr_source, receipt.cvr_source)

    rows = [
        ("Shop name", cell(receipt.shop_name), ""),
        ("Address", cell(receipt.shop_address), shop_src),
        ("CVR", cell(receipt.shop_cvr), cvr_src),
        ("Total (incl. moms)", receipt.amount, ""),
        ("Moms", receipt.moms, ""),
    ]
    body = "".join(
        f"<tr><td><strong>{label}</strong></td><td>{value}</td><td>{source}</td></tr>"
        for label, value, source in rows
    )
    return (
        "<table><thead><tr><th>Field</th><th>Value</th><th>Source</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


# Event handles
def store_upload(upload_path: str | None):
    """Step 1: save the image, show it as the latest receipt, reset the upload area"""
    if not upload_path:
        raise gr.Error("Please upload a receipt image")

    saved = save_upload(upload_path)
    return (
        gr.File(value=None, interactive=False),  # uploader: emptied and locked
        str(saved),  # preview: the image just uploaded
        str(saved),  # saved_path state, used by step 2
        "<p><strong>Extracting receipt data…</strong></p>" + saved_note(saved),
    )


async def process(saved_path: str | None):
    """Step 2: run the extraction on the saved image"""
    if not saved_path:
        raise gr.Error("No saved receipt to extract")

    try:
        receipt = await extract_data_from_receipt(Path(saved_path))
    except Exception as e:
        gr.Warning(f"Extraction failed: {e}")
        return (
            f"<p><strong>Extraction failed:</strong> {escape(str(e))}</p>"
            + saved_note(saved_path)
        )

    return render_receipt(receipt) + saved_note(saved_path)


def unlock_upload():
    """Step 3: make the upload area usable again."""
    return gr.File(interactive=True)


# UI
with gr.Blocks(title="Receipt Extractor") as demo:
    gr.Markdown(
        "# Receipt extractor\n"
        "Upload a photo of a recipt. It is saved and processed automatically"
    )
    saved_path = gr.State()
    with gr.Row():
        with gr.Column(scale=1):
            uploader = gr.File(
                label="Upload receipt",
                elem_id="uploader",
                file_types=["image"],
                file_count="single",
                type="filepath",
                height=140,
            )
            preview = gr.Image(
                label="Receipt",
                type="filepath",
                interactive=False,
                height=420,
            )

        with gr.Column(scale=1):
            extracted_data = gr.HTML(
                value="<p>Upload a receipt to see the extracted data here.</p>",
                label="Extracted data",
                show_label=True,
                container=True,
                elem_id="extracted",
                height=560,
            )

    # Step 1: save + show the image and lock the upload area
    stored = uploader.upload(
        store_upload,
        inputs=uploader,
        outputs=[uploader, preview, saved_path, extracted_data],
        api_name="save",
    )
    # Step 2: extract if step 1 succeeded
    extracted = stored.success(
        process,
        inputs=saved_path,
        outputs=extracted_data,
        show_progress="minimal",
        api_name="extract",
        concurrency_limit=1,  # Number of users allowed at a time
    )
    # Step 3: unlock the upload area
    extracted.then(unlock_upload, outputs=uploader, show_progress="hidden")

if __name__ == "__main__":
    demo.launch(
        inbrowser=True,
        allowed_paths=[str(UPLOAD_DIR.resolve())],
        css=CSS,
    )
