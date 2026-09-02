# data/raw/ — real datasets go here (never committed)

Everything in this folder except this README is gitignored. Drop the corpora
in the layouts below and the adapters in `phase5/dataset_adapters.py` pick
them up with no code changes.

Check what is currently visible:

```
python phase5/dataset_adapters.py
```

## Expected layout

```
data/raw/
  sensor_packets/            # real Ghost State captures — highest fidelity
    normal/*.json
    emergency/*.json
  sisfall/                   # the only source of real falls
    SA01/D01_SA01_R01.txt
    SA01/F01_SA01_R01.txt
  uci_har/
    RawData/acc_exp01_user01.txt
  wisdm/
    WISDM_ar_v1.1_raw.txt
  ravdess/                   # audio only
    Actor_01/03-01-06-01-02-01-01.wav
```

See `../../DATA_REQUIREMENTS.md` for what each corpus does and does not
provide, and why no single one of them is sufficient on its own.
