import sys, json, os

def main():
    vocals_path  = sys.argv[1]
    hf_token     = sys.argv[2]
    min_speakers = int(sys.argv[3])
    max_speakers = int(sys.argv[4])
    output_json  = sys.argv[5]

    os.environ["HF_TOKEN"] = hf_token

    from pyannote.audio import Pipeline
    import torch

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
    )

    if torch.cuda.is_available():
        pipeline = pipeline.to(torch.device("cuda"))

    diarization = pipeline(
        vocals_path,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
    )

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "start":   round(turn.start, 3),
            "end":     round(turn.end,   3),
            "speaker": speaker,
        })

    with open(output_json, "w") as f:
        json.dump(segments, f)

    speakers = set(s["speaker"] for s in segments)
    print(f"[Diarize] Done. {len(segments)} segments, {len(speakers)} speakers: {sorted(speakers)}", flush=True)

if __name__ == "__main__":
    main()
