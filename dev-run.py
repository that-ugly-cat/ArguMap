"""Avvio locale di ArguMap, per guardarlo in un browser.

DB usa-e-getta in `.devdata/`: `ARGUMAP_DB_URL` punta lì, quindi questo script
non ha modo di toccare `data/maps.db`. `JWT_SECRET` è una chiave di sessione
generata al primo giro e tenuta nella stessa cartella, così i login locali
sopravvivono a un riavvio.

`os.chdir(BASE)` non è cosmetico: `main.py` monta `static/`, `imgs/` e
`templates/` con percorsi relativi, quindi la working directory *deve* essere
quella dell'app, qualunque sia quella da cui si lancia.

È uno script Python e non uno shell script per la stessa ragione di borant-id:
l'anteprima lancia bash, che ragiona in `/mnt/c/...`, mentre l'interprete è un
binario Windows. Qui l'interprete è già quello giusto.
"""
import os
import pathlib
import secrets

BASE = pathlib.Path(__file__).resolve().parent
DEV = BASE / ".devdata"
DEV.mkdir(exist_ok=True)

chiave = DEV / "jwt.key"
if not chiave.exists():
    chiave.write_text(secrets.token_urlsafe(48), encoding="utf-8")

os.environ.setdefault("ARGUMAP_DB_URL", "sqlite:///" + str(DEV / "dev.db").replace("\\", "/"))
os.environ.setdefault("JWT_SECRET", chiave.read_text(encoding="utf-8").strip())
os.environ.setdefault("AUTH_MODE", "local")

os.chdir(BASE)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8020)
