"""Quick test to inspect Gradio 6 DOM output for form components."""
import gradio as gr

with gr.Blocks(title="DOM Test", css="""
.md-textbox { border: 3px solid red !important; }
.md-dropdown { border: 3px solid blue !important; }
.md-chip { border: 3px solid green !important; }
""") as demo:
    tb = gr.Textbox(label="Test Input", elem_classes=["md-textbox"], elem_id="test-tb")
    dd = gr.Dropdown(label="Test Dropdown", choices=["a", "b", "c"], elem_classes=["md-dropdown"], elem_id="test-dd")
    cb = gr.Checkbox(label="Test Check", elem_classes=["md-chip"], elem_id="test-cb")
    sl = gr.Slider(label="Test Slider", elem_classes=["md-slider"], elem_id="test-sl")

demo.launch(server_port=7861, share=False)
