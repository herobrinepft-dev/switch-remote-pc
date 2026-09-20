# 🎮 PC Remote — Switch 2 → Windows 11

> **Contrôle ton PC Windows depuis le navigateur de la Nintendo Switch 2.**  
> Écran, son, souris et clavier **en temps réel**, sans installation côté console.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![WebRTC](https://img.shields.io/badge/WebRTC-aiortc-333333?logo=webrtc&logoColor=white)](https://github.com/aiortc/aiortc)
[![Licence](https://img.shields.io/badge/licence-MIT-green)](./LICENSE)

---

## ✨ Fonctionnalités

| | |
|---|---|
| 🖥 **Streaming écran** | WebRTC (**VP8 / H.264**) ou repli **MJPEG** automatique |
| 🔊 **Son du PC** | Capture loopback **WASAPI** — tu entends exactement ce que joue le PC |
| 🖱 **Souris complète** | Clic, double-clic, clic droit, **appui long maintenu**, glisser-déposer, molette |
| ⌨️ **Clavier** | Touches, raccourcis et **saisie Unicode** (accents, emojis, caractères spéciaux) |
| 🎮 **Mode jeu** | Pavé **ZQSD** tactile, compatible **Roblox**, **Unity** et jeux DirectInput |
| 🖥 **Multi-écran** | Bascule à chaud entre **écran 1**, **écran 2**, ou **tous** |
| 🔒 **Maintien / Verrou** | Doigt posé = touche enfoncée, ou **verrou persistant** |
| 🌐 **Zéro installation** | Ouvre simplement une URL — **rien à installer** sur la Switch |

---

## 📋 Prérequis

- **Windows 10 ou 11**
- [**Python 3.10+**](https://www.python.org/downloads/) — cocher **Add python.exe to PATH**
- PC et Switch sur le **même réseau Wi-Fi**
- **Droits administrateur** recommandés (jeux DirectInput)

---

## 🚀 Installation

**1. Clone le dépôt :**

```bash
git clone https://github.com/herobrinepft-dev/pc-remote-switch2.git
cd pc-remote-switch2
```

**2. Double-clique sur `start.bat`.**

Le premier lancement :
- crée un **environnement virtuel**,
- installe les **dépendances**,
- démarre le **serveur**. ⏱️ *~2 minutes, une seule fois.*

**3. Autorise Python dans le pare-feu Windows** → coche **réseaux privés** + **publics**, puis *Autoriser*.

**4. La console affiche :**

```
Sur la Switch 2, ouvre :  http://192.168.1.42:5000
```

---

## 🌐 Accéder au navigateur sur Switch 2

> La Switch n'a **pas de navigateur visible**. Il faut activer le navigateur caché via un **DNS public**.

**1.** **Paramètres** (⚙) → **Internet** → **Paramètres Internet**

**2.** Sélectionne ton **réseau Wi-Fi** → **Modifier les paramètres**

**3.** **Paramètres DNS** : passe de *Automatique* à **Manuel**

**4.** **DNS primaire** : `045.055.142.122` *(le secondaire peut rester vide)*

**5.** Sauvegarde, reconnecte-toi au réseau, puis clique **Suivant** sur l'écran de connexion

**6.** Une page **« Continuer vers Google »** apparaît → clique dessus

**7.** Dans la barre d'adresse, tape l'URL affichée par le serveur :
```
http://192.168.1.42:5000
```

> ⚠️ **Limites du navigateur Switch**
> - La session est **coupée automatiquement après 20 minutes**
> - Certaines fonctions avancées (**YouTube**, **WebRTC**) peuvent ne pas fonctionner
> - Le client bascule alors **automatiquement** en mode **MJPEG + PCM**

---

## 🎯 Utilisation

### 🖱 Souris (sur l'image)

| Geste | Action |
|---|---|
| **Tap rapide** | Clic gauche |
| **Double-tap rapide** | Double-clic |
| **Appui long** (> 400 ms) | Maintient le clic gauche (**drag**, sélection) |
| **Molette** | Défilement |
| Bouton **✋ GLISSER** | Drag immédiat sans attendre |
| Bouton **🖱 CLIC DROIT** | Clic droit |

### 🎮 Mode jeu (bouton **🎮**)

Pavé **ZQSD** + **ESPACE**, **SHIFT**, **E**, **F**, **↵**, **ESC**.

| Mode | Comportement |
|---|---|
| **🔓 MAINTIEN** *(défaut)* | Doigt posé = touche enfoncée · Doigt levé = relâchée |
| **🔒 VERROU** | Un tap enfonce · Un second tap relâche |

> Le bouton **🎮** force aussi la fenêtre du jeu **au premier plan** — indispensable pour **Roblox**.

### 🖥 Choix de l'écran (bouton **🖥**)

Menu déroulant pour basculer entre **écran 1**, **écran 2** ou **tous les écrans**.
**Changement instantané**, sans recharger la page.

---

## ⚙️ Options

```bat
start.bat --option
```

| Option | Effet | Défaut |
|---|---|---|
| `--width 1920` | Largeur max du flux | `1280` |
| `--fps 60` | Images par seconde | `30` |
| `--bitrate 8000` | Débit vidéo (kbit/s) | `4000` |
| `--monitor 2` | Écran à diffuser (0 = tous) | `1` |
| `--port 8080` | Port d'écoute | `5000` |
| `--no-audio` | Désactive le son | — |
| `--no-cursor` | Masque le curseur | — |

---

## 🛠️ Dépannage

| ❌ Problème | ✅ Solution |
|---|---|
| **Pas d'image** | Vérifier pare-feu Windows (**TCP + UDP**), même Wi-Fi, essayer `--width 1280 --fps 30` |
| **Pas de son** | Vérifier sortie audio par défaut · réinstaller : `pip install -U soundcard` |
| **Clics sans effet** | Lancer `start.bat` **en administrateur** |
| **ZQSD ne bouge pas (Roblox)** | `pip install pydirectinput pygetwindow`, lancer en **admin**, appuyer sur **🎮** avant de jouer |
| **Image noire** sur Netflix/DRM | Contenu protégé — **non capturable** (limitation Windows) |
| **Un seul appareil à la fois** | Une nouvelle connexion remplace la précédente |

---

## 🔒 Sécurité

> **⚠️ Aucune authentification.**

**Toute personne** sur ton Wi-Fi peut **voir et contrôler ton PC**. À utiliser uniquement sur un **réseau de confiance**.

- ❌ **Ne jamais** exposer sur Internet (pas de redirection de port, pas de DMZ).
- ✅ Pour un accès distant : **VPN** (Tailscale, WireGuard) ou reverse proxy avec **BasicAuth**.

---

## 🏗️ Architecture

```
pc-remote-switch2/
├── start.bat         # 🚀 Lanceur Windows
├── server.py         # 🐍 Flask + WebRTC + capture + audio + entrées
├── requirements.txt  # 📦 Dépendances Python
└── static/
    └── index.html    # 🌐 Client web
```

| Composant | Technologie |
|---|---|
| **Capture** | `mss` + `PyAV` — VP8/H.264 pour WebRTC, JPEG pour MJPEG |
| **Audio** | `soundcard` — loopback WASAPI, PCM 16 bits 48 kHz |
| **Transport** | WebRTC prioritaire, **repli automatique** MJPEG + PCM |
| **Entrées** | DataChannel WebRTC (ou HTTP en repli), `pydirectinput` pour les jeux DirectInput |

---

## 🤝 Contribuer

**Issues** et **pull requests** bienvenues.

```bash
git clone https://github.com/herobrinepft-dev/pc-remote-switch2.git
cd pc-remote-switch2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

**Pistes d'amélioration :**
- 🔐 Authentification par mot de passe
- 📱 Support multipoint (pincer pour zoomer)
- 🎥 Choix du codec (VP9, AV1)
- 🌍 Interface multilingue
- 📊 Statistiques de latence en direct

---

## 📄 Licence

**MIT** — fais-en ce que tu veux, garde juste la mention de copyright.

---

## 🙏 Crédits

[**aiortc**](https://github.com/aiortc/aiortc) · [**mss**](https://github.com/BoboTiG/python-mss) · [**PyAV**](https://github.com/PyAV-Org/PyAV) · [**pyautogui**](https://github.com/asweigart/pyautogui) · [**pydirectinput**](https://github.com/learncodebygaming/pydirectinput) · [**soundcard**](https://github.com/bastibe/SoundCard) · [**Flask**](https://flask.palletsprojects.com/)

---

<div align="center">

**Fait avec ❤️ pour la Switch 2**

⭐ Mets une étoile si ce projet t'a aidé !

</div>
