# Flask webapp til Pokémon pris-scanner

Denne webapp giver et simpelt website til dit prisopslag i `pokemon_pris_scanner.py`.

## Filer

- `app.py`: Flask-server (UI + JSON endpoint)
- `templates/`: HTML-sider
- `static/styles.css`: styling

## Installation (Windows / PowerShell)

I projektmappen:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Start webserveren

```powershell
.\.venv\Scripts\Activate.ps1
py .\app.py
```

Åbn derefter i browser:

- `http://127.0.0.1:8000/`

## Endpoints

- `GET /`: forside med søgefelt
- `GET /lookup?q=<navn>`: viser resultater i browseren
- `GET /api/lookup?q=<navn>`: samme data som JSON (til integration)

