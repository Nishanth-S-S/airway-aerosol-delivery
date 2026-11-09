# 03 — Particle mass conservation (+ numerical deposition floor)

**Mass balance.** For every particle case: introduced ≈ deposited + escaped + suspended
(target-plane crossings are a transport measure and are *not* added). Checked automatically per case
against `qa.particle_mass_balance_percent`; this study tabulates all cases.

```bash
python scripts/run_validation.py mass
```

**Tracer floor.** 0.1 µm particles (Stokes number ~10⁻⁵) follow the air; any wall deposition they show is
numerical (mesh / interpolation near walls). Subtract-or-report this floor when interpreting 1 µm results.

```bash
python scripts/run_validation.py tracer --geometry healthy --waveform symmetric
```
