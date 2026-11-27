"""Run local Qwen3-TTS in its own Python environment."""

import json
import os
import re
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel
from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem
from safetensors.torch import load_file, save_file


def device_dtype():
    if not torch.cuda.is_available():
        raise ValueError("未检测到可用的 NVIDIA CUDA 显卡。请检查显卡驱动和所选 Python 环境。")
    try:
        torch.ones(1, device="cuda").sum().item()
    except RuntimeError as exc:
        raise ValueError("当前 CUDA 运行环境与显卡不兼容，请更新驱动或选择可用的 Python 环境。") from exc
    return torch.bfloat16 if torch.cuda.is_bf16_supported(including_emulation=False) else torch.float16


def save_prompt(path, embedding, codes):
    if embedding.ndim != 1 or not embedding.is_floating_point() or not torch.isfinite(embedding).all():
        raise ValueError("音色文件缺少有效的声音特征。")
    if codes is None or codes.ndim != 2 or codes.shape[1] != 16 or codes.is_floating_point():
        raise ValueError("音色文件缺少有效的参考语音编码。")
    save_file({"speaker": embedding.detach().to(device="cpu", dtype=torch.float32).contiguous(),
               "reference": codes.detach().to(device="cpu", dtype=torch.int64).contiguous()}, path)


def split_text(text, limit=140):
    pieces = []
    for sentence in re.findall(r"[^。！？!?；;\n]+[。！？!?；;]*|[。！？!?；;]", text):
        sentence = sentence.strip()
        while len(sentence) > limit:
            boundary = max(sentence.rfind(ch, limit // 2, limit) for ch in "，、, ") + 1
            boundary = boundary or limit
            pieces.append(sentence[:boundary].strip())
            sentence = sentence[boundary:].strip()
        if sentence:
            if pieces and len(pieces[-1]) + len(sentence) < limit and not pieces[-1].endswith(tuple("。！？!?")):
                pieces[-1] += " " + sentence
            else:
                pieces.append(sentence)
    return pieces


def generate(model, job):
    saved = load_file(job["profile"])
    speaker = saved["speaker"]
    icl = job["mode"] == "icl"
    prompt = VoiceClonePromptItem(ref_code=saved["reference"] if icl else None, ref_spk_embedding=speaker,
                                 x_vector_only_mode=not icl, icl_mode=icl,
                                 ref_text=job["reference_text"] if icl else None)
    segments = split_text(job["text"])
    sample_rate = None
    with sf.SoundFile(job["output"], "w", samplerate=24000, channels=1, subtype="PCM_24") as output:
        for segment in segments:
            wavs, rate = model.generate_voice_clone(text=segment, language=job["language"], voice_clone_prompt=[prompt],
                                                   non_streaming_mode=True, max_new_tokens=1100,
                                                   temperature=0.75, repetition_penalty=1.1)
            wave = np.asarray(wavs[0], dtype=np.float32)
            if rate != output.samplerate or wave.ndim != 1 or not wave.size or not np.isfinite(wave).all() or not np.any(wave):
                raise ValueError("模型没有生成有效的配音。请尝试缩短文案或更换参考录音。")
            if sample_rate:
                output.write(np.zeros(round(rate * 0.16), dtype=np.float32))
            wave *= min(1., .98 / float(np.abs(wave).max()))
            fade = min(round(rate * .008), wave.size // 2)
            if fade:
                wave[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
                wave[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
            output.write(wave)
            sample_rate = rate
        if not sample_rate:
            raise ValueError("请填写可朗读的文案。")
        return {"duration": output.tell() / sample_rate}


def execute(job):
    action = job["action"]
    if action == "import":
        profile = torch.load(job["legacy"], map_location="cpu", weights_only=True)
        item, = profile["items"]
        if not isinstance(item.get("ref_spk_embedding"), torch.Tensor) or item["ref_spk_embedding"].shape != (2048,):
            raise ValueError("这个旧音色与 Qwen3-TTS 1.7B Base 不兼容，请用原录音重新创建。")
        ref_text = item["ref_text"] or profile.get("ref_text")
        if not isinstance(ref_text, str) or not ref_text.strip() or len(ref_text) > 2000:
            raise ValueError("旧音色缺少有效的参考原文。")
        save_prompt(job["profile"], item["ref_spk_embedding"], item["ref_code"])
        return {"reference_text": ref_text.strip()}

    if action == "probe":
        device_dtype()
        return {"device": torch.cuda.get_device_name(0)}

    torch.set_num_threads(min(6, os.cpu_count() or 4))
    model = Qwen3TTSModel.from_pretrained(job["model"], device_map="cuda:0", dtype=device_dtype(),
                                         attn_implementation="sdpa", local_files_only=True)
    if action == "clone":
        reference, rate = sf.read(job["reference"], dtype="float32")
        item, = model.create_voice_clone_prompt(ref_audio=(reference, rate), ref_text=job["reference_text"])
        save_prompt(job["profile"], item.ref_spk_embedding, item.ref_code)
        return {}
    return generate(model, job)


if __name__ == "__main__":
    try:
        print(json.dumps(execute(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))), ensure_ascii=False), flush=True)
    except torch.cuda.OutOfMemoryError:
        sys.exit("显存不足。请关闭其他占用显存的软件，或使用较小的 0.6B 模型创建音色。")
    except ValueError as exc:
        sys.exit(str(exc))
