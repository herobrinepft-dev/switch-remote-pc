# PC Remote (Switch 2 → Windows 11)

Affiche l'écran de ton PC **avec le son** dans le navigateur de la Switch 2 et permet de le contrôler.

## Utilisation
1. Double-clique sur **start.bat** (le premier lancement installe tout, ça prend quelques minutes).
2. Autorise Python dans le **pare-feu Windows** (réseau privé) quand la fenêtre apparaît.
3. La console affiche l'adresse : ouvre-la sur la Switch. Il n'y a pas de mot de passe.

## Commandes dans la page
- **Tape** sur l'image = clic gauche · **appui long** = clic droit · **glisse** = déplace le curseur.
- **✋ GLISSER** : les glissements maintiennent le clic (déplacer une fenêtre, sélectionner...).
- ▲ ▼ : défilement (reste appuyé pour défiler en continu) · molette de souris aussi.
- Zone de texte : tape n'importe quoi (accents, emojis) puis *Envoyer* ou Entrée.
- 🔊 / ⛶ / ⌨ en haut à droite : son, plein écran, masquer les commandes.

## Options (`start.bat --option`)
| Option | Effet |
|---|---|
| `--width 1920` | image plus nette (défaut 1280) |
| `--fps 60` | plus fluide (défaut 30) |
| `--bitrate 8000` | débit vidéo en kbit/s (défaut 4000) |
| `--monitor 2` | diffuser le 2ᵉ écran |
| `--no-audio` / `--no-cursor` | sans son / sans curseur dessiné |
| `--port 8080` | changer de port |

## Si ça ne marche pas
- **Pas d'image** : pare-feu Windows (Python doit être autorisé en TCP **et** UDP), et PC + Switch sur le même Wi-Fi.
- **Pas de son** : le message de la console indique pourquoi. Vérifie qu'une sortie audio par défaut existe, puis
  `.venv\Scripts\pip install -U soundcard`. Le son se joue aussi sur le PC (loopback), baisse-le si besoin.
- **Image noire** sur un film/jeu : certains contenus protégés (DRM) ne peuvent pas être capturés.
- **Les clics n'agissent pas** sur une fenêtre « administrateur » ou l'écran UAC : lance `start.bat` en administrateur.
- Un seul appareil à la fois : une nouvelle connexion remplace la précédente.
- **Sécurité** : sans mot de passe, toute personne sur ton réseau Wi-Fi peut voir et contrôler le PC. À utiliser sur un réseau de confiance, et ne l'expose jamais sur Internet (ni redirection de port).
