# Bep-Project — Volledige Run Guide

Stappenplan om vanaf een schone laptop tot een gekalibreerde 3D-meting te komen. Volg de stappen in volgorde — overslaan kan, maar dan zijn de coördinaten in je CSV niet betrouwbaar.

---

## Inhoud

1. [Eénmalige setup](#1-eenmalige-setup)
2. [Hardware aansluiten](#2-hardware-aansluiten)
3. [Arduino firmware flashen](#3-arduino-firmware-flashen)
4. [UI starten en verbinden](#4-ui-starten-en-verbinden)
5. [Soft-home: motoren op 0 zetten](#5-soft-home-motoren-op-0-zetten)
6. [Eénmalige mm/stap-kalibratie](#6-eenmalige-mmstap-kalibratie)
7. [Een meting opnemen — handmatig](#7-een-meting-opnemen)
8. [Automatische raster-scan](#8-automatische-raster-scan) ⭐
9. [3D-resultaten bekijken](#9-3d-resultaten-bekijken)
10. [Volgende sessie — wat onthoudt het systeem?](#10-volgende-sessie--wat-onthoudt-het-systeem)
11. [Probleemoplossing](#11-probleemoplossing)

---

## 1. Eénmalige setup

Doe dit één keer per laptop.

### Python-omgeving

```powershell
cd C:\Users\Test\Documents\GitHub\Bep-Project
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Dit installeert PySide6, pyserial, opencv-python, matplotlib, pandas, numpy, scipy, sympy, pyyaml, moku.

### Arduino IDE

1. Download Arduino IDE 2.x van https://www.arduino.cc/en/software en installeer.
2. Open de IDE en ga naar **Tools → Manage Libraries...** en installeer:
   - **`Adafruit NeoPixel`**
   - **`AccelStepper`**

### CH340-driver (alleen bij clone-Nano)

Als de Nano niet als COM-poort verschijnt: download de CH340-driver van https://www.wch-ic.com/downloads/CH341SER_EXE.html en installeer.

---

## 2. Hardware aansluiten

```
┌─────────────────────────────────────────────────────────┐
│                   Arduino Nano                          │
│                                                         │
│  USB → laptop (COM4 of COM5, hangt van Windows af)      │
│                                                         │
│  D2/D5  → Stepper-driver Motor 1 (STEP/DIR)             │
│  D3/D6  → Stepper-driver Motor 2                        │
│  D4/D7  → Stepper-driver Motor 3                        │
│  D8     → ENABLE alle drivers (active LOW)              │
│  A2     → DIN van WS2812B (via 470 Ω)                   │
│  5V     → VCC WS2812B + drivers logic                   │
│  GND    → GND alles                                     │
└─────────────────────────────────────────────────────────┘

  Moku:Go     → Ethernet/USB → laptop, IP 192.168.73.1
  USB-camera  → laptop (index 0)
  WS2812B-8   → DIN op A2, VCC op 5V, GND op GND
```

**Checks vóór je inschakelt:**
- WS2812B-pijltje op de print wijst van de Nano af (anders brandt de ring niet)
- Stepper-driver Vmot voeding matcht je motor (vaak 12V, los van Nano-USB)
- Geen losse draden die kortsluiting kunnen maken

---

## 3. Arduino firmware flashen

Doe dit één keer, en opnieuw alleen als je de firmware wijzigt.

1. **Sluit de UI af** (`python ui.py` mag niet draaien — anders is COM-poort bezet).
2. Open **Arduino IDE**.
3. **File → Open** → navigeer naar `arduino\firmware\firmware.ino` in dit project.
4. Selecteer board:
   - **Tools → Board → Arduino AVR Boards → Arduino Nano**
   - **Tools → Processor → ATmega328P** (bij upload-fout: switch naar `ATmega328P (Old Bootloader)`)
   - **Tools → Port → COMx** (kies de poort waar de Nano op staat)
5. **Ctrl+R** om te compileren — verwacht "Done compiling".
6. **Ctrl+U** om te uploaden — verwacht "Done uploading".

**Sanity-test** (optioneel maar aanbevolen):

Open in de IDE de Serial Monitor (vergrootglas-icoon, baud `9600`, line ending `Both NL & CR`):

| Typ | Verwacht antwoord | Wat je controleert |
|---|---|---|
| (niets — net na reset) | `READY` | Firmware draait |
| `WHERE` | `POS 0 0 0` | WHERE-commando werkt |
| `LAMP 200` | `OK LAMP 200` | Lamp brandt fel |
| `LAMP 0` | `OK LAMP 0` | Lamp uit |
| `SETPOS 1 100` | `OK SETPOS 1 100` | Soft-home werkt |
| `WHERE` | `POS 100 0 0` | SETPOS heeft effect gehad |
| `1 0` | `OK 1 0` | Motor 1 draait fysiek terug naar 0 |
| `STOP` | `OK STOP` | Noodstop werkt |

**Sluit daarna de Serial Monitor** — anders kan de UI de poort niet openen.

---

## 4. UI starten en verbinden

```powershell
.venv\Scripts\Activate.ps1
python ui.py
```

Het venster bestaat uit vier panelen:
- **Linksboven**: live-camera
- **Rechtsboven**: Stepper motors (per motor: jog ↑↓, mm/stap-veld, "Zet 0 hier")
- **Rechtsmidden**: Lamp (slider 0–255)
- **Rechtsonder**: Opname (Record-knop, run-naam)
- **Onder**: Moku:Go fotodetector (live-grafiek)

**Verbinden:**

1. In **MotorPanel** rechtsboven, kies de juiste **COM-poort** uit de dropdown.
2. Klik **Verbind**.
3. De camera staat al aan zodra de UI start.
4. In **MokuPanel** onder: vul IP `192.168.73.1` in (of wat jouw Moku heeft), kanaal/range/coupling, klik **Verbind**.
5. In **LampPanel**: sleep slider om te controleren of de WS2812B-ring meedimt.

Status moet groen zijn ("Verbonden met COM4 @ 9600 baud") in zowel motor- als Moku-paneel.

---

## 5. Soft-home: motoren op 0 zetten

Hierdoor leg je vast wat het **fysieke nulpunt** van je opstelling is. Vanaf dat moment zijn alle motor-posities relatief aan die referentie.

**Per motor:**

1. Beweeg de motor met de **↑/↓-knoppen** tot het preparaat (of de markering) onder het kruisdraadje van de camera ligt — of welk fysiek referentiepunt jij gekozen hebt.
2. Klik **"Zet 0 hier"** naast die motor.
3. Het label springt naar `target: 0` (en `+0.0000 mm` zodra je mm/stap hebt ingevuld).

Doe dit voor alle drie de motoren.

> **Tip**: kies een referentiepunt dat je makkelijk terugvindt — bv. een kruis dat je op het preparaat hebt getekend, of de hoek van een gridje. Het hoeft niet exact in het midden te zijn — als jij maar weet "dit is mijn (0,0,0)".

---

## 6. Eénmalige mm/stap-kalibratie

Doe dit één keer per opstelling. Bewaar daarna gewoon `calibration.yaml`.

**Doel**: omrekenen van "stappen" naar "mm" zodat je 3D-plot in fysieke eenheden staat.

**Per as:**

1. Soft-home de motor (Zet 0 hier).
2. Plaats een schuifmaat / kalibratie-rooster onder het objectief, of meet op een bekende afstand.
3. Stel een grote stapgrootte in (bv. 1000 stappen) en jog éénmaal in `+`-richting.
4. Lees de fysieke afstand: bv. **0.500 mm**.
5. Bereken: `mm/stap = 0.500 / 1000 = 0.0005`.
6. Vul deze waarde in het **mm/stap**-veld naast die motor.
7. Het target-label toont nu: `target: 1000 (+0.5000 mm)` — sanity check.

Herhaal voor motor 2 en 3.

**Sla op:**

- Klik **💾 Save kalibratie**.
- Status: `Kalibratie opgeslagen → calibration.yaml`.

Vanaf nu staat in `calibration.yaml`:

```yaml
motors:
  - mm_per_step: 0.0005
    last_position: 0
    note: ''
  - mm_per_step: 0.000625
    last_position: 0
    note: ''
  - mm_per_step: 0.001
    last_position: 0
    note: ''
saved_at: '2026-05-04T14:30:00'
```

---

## 7. Een meting opnemen

### Voorbereiding per meting

1. **Lamp** op gewenste helderheid via slider (bv. 128).
2. **Moku** moet verbonden zijn — je ziet de live-grafiek lopen.
3. **Run-naam** invullen in het Opname-paneel (bv. `preparaat_A_z0`).

### Opname starten

4. Klik **● Record**. De knop wordt rood en het label toont `■ Stop`.
5. Status: `Opname loopt → data\2026-05-04_14-32-15_preparaat_A_z0\measurement.csv`.

### Tijdens de opname

6. Beweeg de motoren naar verschillende posities. **Wacht tussen punten op stilstand** voor een scherpe 3D-kaart.
7. Per Moku-frame (~10/sec) wordt een rij weggeschreven met:
   - Tijd (ISO + elapsed)
   - Motor 1/2/3 in stappen + in mm
   - Lamp-helderheid
   - Spannings-samenvatting (`V_mean`, `V_min`, `V_max`, `V_std`, `V_pp`)
   - Aantal samples per frame

### Werkpatronen voor scans

| Type meting | Hoe te bewegen |
|---|---|
| **2D raster** (klassiek confocal) | Motor 1 stapsgewijs van −X naar +X, op elke positie motor 2 van −Y naar +Y, kort wachten op stilstand, weer terug |
| **Lijn-scan** | 1 motor langs een lijn, andere 2 stilhouden |
| **Z-stack** | Motor 3 (focus) langzaam variëren, motor 1+2 stil |
| **Vrije scan** | Beweeg ad-hoc tussen interessante posities — viewer aggregeert duplicaten automatisch |

### Opname stoppen

8. Klik **■ Stop**. Status wordt grijs: `Opname gestopt — N rijen.`
9. Klik **Open folder** om de output direct te bekijken.

In `data\<datum>_<tijd>_<naam>\` vind je:
- `measurement.csv` — de data
- `metadata.txt` — tijdstempel, Moku-config, mm/stap, start-positie

---

## 8. Automatische raster-scan

In plaats van handmatig motoren bewegen + Record klikken, kan het Scan-paneel de hele meting **autonoom** uitvoeren. Het paneel zit onderaan rechts in de UI ("Automatische scan").

### Wat de scan-controller doet

Voor elk rasterpunt:
1. Stuurt `GOTO x y z` zodat alle drie de motoren tegelijk vertrekken
2. Pollt elke 80 ms met `BUSY?` tot alle motoren stilstaan
3. Wacht een instelbare **settle time** (trillingen uitdoven)
4. Verzamelt **N achtereenvolgende Moku-frames** en middelt ze
5. Schrijft één rij naar `data/scan_<datum>_<naam>/measurement.csv`
6. Volgende punt — UI blijft de hele tijd responsief (camera, lamp, status)

### Voorbereiding

Voor je een scan start moet:
- Motoren **verbonden** zijn (groene status in MotorPanel)
- Motoren **gekalibreerd** zijn (mm/stap > 0 voor M1 en M2 — en M3 als je Z-stack gebruikt)
- Motoren staan **op het midden** van het te scannen gebied (zet ze handmatig waar je het sample wilt centreren — de scan-controller pakt het huidige (M1, M2)-target als middenpunt)
- **Moku verbonden** en data zichtbaar in de live-grafiek

### Scan-instellingen

| Veld | Wat het doet |
|---|---|
| **Naam** | Subfolder-naam: `data/scan_<tijd>_<naam>/` |
| **Preset** | Snel een set instellingen kiezen (zie hieronder) |
| **Grootte X/Y** (mm) | Totale fysieke afmetingen van het scan-vlak |
| **Punten X/Y** | Hoeveel rasterpunten per as. Step-size = grootte / (punten−1) |
| **Settle (ms)** | Wachttijd na motor-stilstand voor data verzamelt — laat trillingen uitdoven |
| **Frames/punt** | Aantal Moku-frames dat per punt wordt gemiddeld — meer = schoner, langzamer |
| **Snake-pad** | Aan = scan loopt heen-en-weer (sneller, minder backlash). Uit = altijd L→R (ongewenste hard-return aan eind van rij) |
| **Z-stack** | Aan = sweep ook M3 door focus-range. Uit = M3 stilhouden op huidige positie |
| **Z-min, Z-max, Z-stappen** | Range en aantal Z-niveaus (alleen als Z-stack aan) |

Helemaal rechts staat live de **schatting**: aantal punten en geschatte tijd.

### Presets

In `scan_presets.yaml` (project-root) staan defaults:
- **Klein 1×1 mm** — 20×20 punten, 100 ms settle, 3 frames/pt — ~3 min
- **Middel 5×5 mm** — 50×50, 200 ms, 5 frames/pt — ~17 min
- **Groot 10×10 mm** — 100×100, 200 ms, 5 frames/pt — ~70 min

Je eigen preset opslaan: stel alle velden in, klik **"Opslaan als preset…"**, geef een naam (bv. *"Preparaat A — fluorescentie"*). Hij verschijnt vanaf nu in de dropdown.

### Scan starten

1. Klik op **▶ Start scan**.
2. Pre-flight checks: niet verbonden? niet gekalibreerd? Moku niet aan? → waarschuwing, scan start niet.
3. Bij groen licht: status springt naar `Scan gestart → measurement.csv (2500 punten)`, knoppen-blok wordt grijs (instellingen kun je niet meer wijzigen tijdens scan).
4. Voortgangsbalk + statuslabel updaten per punt: `Punt 124/2500 (ix=24, iy=2)`.

### Scan annuleren

Klik **■ Cancel**. De controller:
- Stopt timers
- Stuurt `STOP` naar de Arduino zodat motoren niet doorrijden
- Schrijft de tot dan toe verzamelde rijen + sluit CSV
- Voegt `canceled: True` en `completed_points: N` toe in `metadata.txt`

Je hebt dus alsnog een bruikbare partial-CSV — gewoon openen met de viewer.

### Wat eindigt er in `measurement.csv`?

Per scan-punt **één rij** (in tegenstelling tot de manuele Recording die per Moku-frame een rij schrijft):

| Kolom | Voorbeeld | Betekenis |
|---|---|---|
| `t_iso` | `2026-05-04T15:42:18.213` | Wanneer dit punt afgerond werd |
| `scan_point` | `124` | Volgnummer (0-based) |
| `ix`, `iy`, `iz` | `24`, `2`, `0` | Raster-indices |
| `motor1`, `motor2`, `motor3` | `1240`, `−500`, `0` | Stappen (absoluut) |
| `motor1_mm`, `motor2_mm`, `motor3_mm` | `0,62000`, `−0,25000`, `0,00000` | Hetzelfde in mm |
| `lamp` | `128` | Helderheid op moment van scan |
| `V_mean`, `V_min`, `V_max`, `V_std`, `V_pp` | (samenvattingen over alle samples van alle frames) | Spannings-statistiek |
| `n_frames_averaged` | `5` | Aantal Moku-frames in dit punt gemiddeld |
| `settle_ms` | `200` | Settle-waarde gebruikt |

### Tips

- **Eerste scan**: doe een kleine (10×10 punten, 1×1 mm) om je settle-time en frames/punt af te stemmen. Bij teveel trillingen → settle hoger. Bij ruis-pieken → frames omhoog.
- **Camera blijft live** tijdens scan — handig om visueel te volgen waar het kruisje is.
- **Lamp tijdens scan**: zet hem op één vaste helderheid voor consistente verlichting. Heb je per punt verschillende belichting nodig, dan moet je dat scripten (niet in v1).
- **Sample-grootte aanpassen**: voor elk type sample maak je een nieuwe preset. De software-pipeline blijft hetzelfde, alleen de mm-waarden veranderen.
- **Drift bij lange scans (>30 min)**: thermische uitzetting kan tot tientallen µm verschuiving geven. Houd je raster ruim of doe meerdere kortere scans en overlay achteraf.

### Voorbeeld-workflow voor een nieuw sample-type

1. Plaats sample, soft-home (sectie 5) — middenpunt van sample wordt (0, 0).
2. Eik mm/stap als nieuw mechanisme (sectie 6) — alleen nodig als sample-houder geïsoleerd verandert; meestal blijft dit hetzelfde.
3. Open Scan-paneel, vul afmetingen + resolutie in, klik **"Opslaan als preset…"** met naam *"Type X klein"*.
4. ▶ Start scan. Wacht. CSV verschijnt automatisch in `data/`.
5. `python viewer.py data/<scan-folder>/measurement.csv` voor 3D-plot.

---

## 9. 3D-resultaten bekijken

In een **aparte terminal** (UI mag blijven draaien):

```powershell
.venv\Scripts\Activate.ps1
python viewer.py data\2026-05-04_14-32-15_preparaat_A_z0\measurement.csv
```

Je krijgt twee subplots in één figuur:
- **Links**: 3D-oppervlak — Motor 1 (X) × Motor 2 (Y) → V_mean (Z = hoogte)
- **Rechts**: 2D-heatmap — zelfde data van bovenaf, kleur = V_mean

### Andere metrics

```powershell
python viewer.py data\<run>\measurement.csv --metric V_pp     # piek-tot-piek (bv. ruis-mapping)
python viewer.py data\<run>\measurement.csv --metric V_std    # standaarddeviatie
python viewer.py data\<run>\measurement.csv --metric V_max    # piekwaarde
```

### Eenheid forceren

```powershell
python viewer.py data\<run>\measurement.csv --unit steps      # forceer stappen
python viewer.py data\<run>\measurement.csv --unit mm         # forceer mm (default als gekalibreerd)
```

### Zelf data analyseren

De CSV opent direct in **Excel** — `;`-gescheiden, NL-decimaal.

In Python:

```python
import pandas as pd
df = pd.read_csv("data/2026-05-04_14-32-15_preparaat_A_z0/measurement.csv",
                 sep=";", decimal=",")
print(df.head())
print(df.describe())
```

---

## 10. Volgende sessie — wat onthoudt het systeem?

### Wat ER WEL persistent is

`calibration.yaml` in de project-root onthoudt:
- `mm_per_step` per motor (eik blijft geldig)
- `last_position` per motor (laatste bekende positie bij disconnect)
- `saved_at` (tijdstempel)

### Wat ER NIET persistent is

- De fysieke positie van de motoren (de Nano kan resetten bij upload of stroomverlies)
- Live Moku-data (alleen live)
- Camera-frame (alleen live)

### Wat gebeurt er bij Verbind in de tweede sessie?

De UI:
1. Laadt `calibration.yaml` automatisch.
2. Vraagt firmware via `WHERE` naar de actuele positie.
3. **Vergelijkt**:

| Situatie | Wat gebeurt er |
|---|---|
| Firmware-positie = `last_position` | Niets, "posities consistent met kalibratie". Klaar om te meten. |
| Firmware-positie ≠ `last_position` | **Restore-prompt** verschijnt: "Heb je de motoren NIET fysiek bewogen?" |
| → **Ja** | UI stuurt `SETPOS` voor elke motor → eik wordt hersteld zonder beweging |
| → **Nee** | Behoud firmware-positie. Eik opnieuw via "Zet 0 hier". |

> **Vuistregel**: als je tussen sessies de motoren niet hebt verschoven (ook geen Arduino-upload of stroom-uit gehad), kies **Ja**. Bij twijfel: **Nee** + opnieuw soft-homen.

---

## 11. Probleemoplossing

### Upload-fouten in Arduino IDE

| Foutmelding | Oplossing |
|---|---|
| `can't set com-state for COMx` | UI of Serial Monitor heeft de poort open. Sluit ze af. USB ontkoppelen + opnieuw aansluiten. |
| `not in sync: resp=0x22` met `ATmega328P (Old Bootloader)` | Switch naar **`ATmega328P`** (zonder Old Bootloader). |
| `not in sync` met `ATmega328P` | Switch naar **`ATmega328P (Old Bootloader)`**. |
| `Port busy` / `Access denied` | Iets anders heeft COM open: Serial Monitor, PuTTY, andere `python.exe`. Task Manager → kill. |
| Geen COM-poort zichtbaar | USB-kabel is power-only zonder data. Probeer een andere kabel. CH340-driver checken. |

### COM-poort verandert tussen runs

Windows hernummert soms de Nano (COM3 → COM4 → COM5). Dit gebeurt vooral na unplug/replug.

- Selecteer de juiste poort in de **MotorPanel-dropdown**.
- Wil je een andere default? Pas in [ui.py](../ui.py) regel 45 aan: `DEFAULT_PORT = "COMx"`.

### Lamp brandt niet

1. Check bedrading: DIN op A2, pijltje op de print **van de Nano af**, 5V op VCC, GND op GND.
2. Test in Arduino Serial Monitor: `LAMP 200`. Als geen reactie → flash-firmware ontbreekt of pin-define fout.
3. 470 Ω weerstand in DIN-lijn aanwezig? Zonder werkt het soms wel, soms niet.

### Motoren bewegen verkeerde kant op

- Wissel de DIR-richting in de firmware (`m1` → `-m1` is *niet* hoe het werkt — gebruik `m1.setPinsInverted(true, false, false)` in `setup()`).
- Of fysiek de DIR-draad omdraaien.

### Restore-prompt komt elke verbind, ook al heb ik niets bewogen

- DTR-onderdrukking werkt niet op alle CH340-clones.
- Workaround: na elke "Verbind" gewoon **Ja** kiezen op de prompt. Het is veilig — `SETPOS` zet alleen de teller, beweegt niet.
- Als alternatief: gebruik een echte FTDI-Nano (geen clone) — DTR-onderdrukking is daar betrouwbaarder.

### CSV is leeg of slechts header

- Moku is niet verbonden tijdens opname — er zijn geen frames om te loggen.
- Check Moku-status in MokuPanel: moet groen zijn ("Verbonden met …").

### `viewer.py` toont waarschuwing "minder dan 2 unieke posities"

- Je hebt tijdens de opname maar één punt bemeten. Beweeg motoren naar verschillende `(motor1, motor2)`-coördinaten voor een echt 3D-oppervlak.

### `calibration.yaml` is corrupt

Verwijder hem — de UI maakt automatisch een nieuwe lege bij de volgende save. Je kalibratie ben je dan wel kwijt.

---

## Snelreferentie — alle commando's voor de firmware

| Commando | Effect | Antwoord |
|---|---|---|
| `<n> <p>` (n = 1/2/3) | Motor n naar absolute positie p stappen | `OK <n> <p>` |
| `GOTO <m1> <m2> <m3>` | Alle 3 motoren tegelijk naar absolute target | `OK GOTO <m1> <m2> <m3>` |
| `SPEED <v>` | Max snelheid voor alle motoren (stappen/s) | `OK SPEED <v>` |
| `STOP` | Noodstop, alle motoren | `OK STOP` |
| `LAMP <0-255>` | WS2812B-helderheid | `OK LAMP <n>` |
| `SETPOS <m> <n>` | Soft-home: zet positie zonder beweging | `OK SETPOS <m> <n>` |
| `WHERE` | Vraag actuele posities op | `POS <m1> <m2> <m3>` |
| `BUSY?` | Vraag of motoren nog rijden | `BUSY 1` of `BUSY 0` |

Bij start: `READY`.

---

## Bestandsstructuur na een sessie

```
Bep-Project/
├── ui.py
├── recording.py              ← handmatig: per Moku-frame loggen
├── scan.py                   ← automatisch raster-scan
├── calibration.py
├── lamp.py
├── viewer.py
├── calibration.yaml          ← jouw eik (commit niet)
├── scan_presets.yaml         ← scan-presets per sample-type (commit niet)
├── arduino/firmware/firmware.ino
└── data/
    ├── 2026-05-04_14-32-15_preparaat_A_z0/         ← handmatige opname
    │   ├── measurement.csv
    │   └── metadata.txt
    ├── scan_2026-05-04_15-10-02_preparaat_A_5x5/   ← auto-scan
    │   ├── measurement.csv
    │   └── metadata.txt
    └── ...
```

Handmatige opnames krijgen `<datum>_<naam>/`, automatische scans krijgen `scan_<datum>_<naam>/`. Beide CSV's openen met dezelfde `viewer.py`.

Eén map per opname. CSV's zijn klein (~1 MB/uur), je kunt er gerust honderden bewaren.
