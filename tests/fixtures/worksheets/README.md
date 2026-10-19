# Bewertungsbögen im alten Format

`kalibrierbogen_format1_ausgefuellt.xlsx` — aufgenommen am 2026-10-19.

Erzeugt mit `scripts/worksheet_xlsx.py export` im Stand von `main` vor
Format 2, aus `eval/claim_prefill_calibration.json` unter Regelversion
1.3.0. Genau so ein Bogen ging an die Bewertenden der Kalibrierrunde.
Danach ausgefüllt wie von einer bewertenden Person: Name, Datum und
«Blind bewertet?» an den alten Protokollzellen C12–C14, dazu eine Antwort
im ersten Fall.

Der Test `LegacyFormatTests` liest die Datei mit dem aktuellen Import. Er
belegt, dass ein Bogen im alten Layout nach einer Änderung am Blatt
«Anleitung» weiterhin eingelesen wird. Die Datei wird nicht neu erzeugt:
Ihr Wert liegt darin, dass sie aus dem alten Exporter stammt.
