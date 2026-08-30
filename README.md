# Versatile Video Downloader

A powerful and versatile command-line video downloader written in Python. It supports downloading publicly available, non-DRM protected content from numerous platforms.

## Features

*   **Download Videos:** Download from any platform supported by `yt-dlp`.
*   **Format Selection:** Choose between `mp4`, `mkv`, or let the tool pick the `best` format.
*   **Quality Selection:** Specify video quality (`best`, `1080p`, `720p`, `480p`, `worst`).
*   **Audio Extraction:** Extract audio only and save it as an MP3 file.
*   **Subtitles:** Automatically download subtitles when available.
*   **Batch Downloading:** Read multiple URLs from a text file to download in bulk.
*   **Playlist Control:** Choose whether to download an entire playlist or just a single video.
*   **Metadata Embedding:** Embed video metadata (title, author) and thumbnails directly into the downloaded file.
*   **Custom Output Naming:** Customize the output file name template.

## Requirements

*   Python 3.6 or higher
*   `yt-dlp`
*   `pytest` (for running tests)
*   `ffmpeg` (highly recommended for format conversion and audio extraction)

## Installation

1.  Clone this repository or download the source files.
2.  Install the required Python packages:

```bash
pip install -r requirements.txt
```

3.  Ensure `ffmpeg` is installed on your system.
    *   **Ubuntu/Debian:** `sudo apt install ffmpeg`
    *   **macOS:** `brew install ffmpeg`
    *   **Windows:** Download from the official site and add it to your PATH.

## Usage

Run the `downloader.py` script from the `src` directory:

```bash
python3 src/downloader.py [options] [URL]
```

### Options

*   `URL`: The URL of the video to download (Optional if `--batch-file` is provided).
*   `-a`, `--batch-file`: File containing URLs to download, one per line.
*   `-f`, `--format`: Specify the desired video format (`mp4`, `mkv`, `best`). Default is `best`.
*   `-q`, `--quality`: Specify the desired video quality (`best`, `1080p`, `720p`, `480p`, `worst`). Default is `best`.
*   `--extract-audio`: Extract audio only (saves as MP3).
*   `--subtitles`: Download subtitles if available.
*   `--no-playlist`: Download only the single video, ignoring the rest of the playlist if the URL is part of one.
*   `--embed-metadata`: Embed video metadata (title, artist, etc.) in the output file.
*   `--embed-thumbnail`: Embed the video's thumbnail as cover art.
*   `-o`, `--output`: Output filename template (e.g., `%(title)s.%(ext)s`).

### Examples

**Download a video with default settings (best quality):**
```bash
python3 src/downloader.py "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download a video in 720p MP4 format:**
```bash
python3 src/downloader.py -f mp4 -q 720p "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Extract only the audio as an MP3:**
```bash
python3 src/downloader.py --extract-audio "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download a video with subtitles and save to a specific directory:**
```bash
python3 src/downloader.py --subtitles -o "~/Downloads/%(title)s.%(ext)s" "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download a video with embedded metadata and thumbnail:**
```bash
python3 src/downloader.py --embed-metadata --embed-thumbnail "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download multiple videos from a text file (e.g., `urls.txt`):**
```bash
python3 src/downloader.py -a urls.txt
```

## Testing

To run the automated tests, execute `pytest` from the root directory:

```bash
pytest tests/
```

## Disclaimer

This tool is intended solely for downloading unprotected, publicly available content. It does not bypass Digital Rights Management (DRM) or download protected content from commercial streaming platforms. Users are responsible for ensuring they have the legal right to download and use the content they access with this tool.

---

# Versatile Video Downloader (Français)

Un puissant et polyvalent téléchargeur de vidéos en ligne de commande, écrit en Python. Il prend en charge le téléchargement de contenu accessible au public et non protégé par DRM depuis de nombreuses plateformes.

## Fonctionnalités

*   **Téléchargement de vidéos :** Téléchargez depuis n'importe quelle plateforme prise en charge par `yt-dlp`.
*   **Sélection du format :** Choisissez entre `mp4`, `mkv`, ou laissez l'outil choisir le `best` (meilleur) format.
*   **Sélection de la qualité :** Spécifiez la qualité vidéo (`best`, `1080p`, `720p`, `480p`, `worst`).
*   **Extraction audio :** Extrayez uniquement l'audio et enregistrez-le sous forme de fichier MP3.
*   **Sous-titres :** Téléchargez automatiquement les sous-titres lorsqu'ils sont disponibles.
*   **Téléchargement par lots :** Lisez plusieurs URL à partir d'un fichier texte pour un téléchargement groupé.
*   **Contrôle des playlists :** Choisissez de télécharger une playlist entière ou juste une seule vidéo.
*   **Intégration des métadonnées :** Intégrez les métadonnées de la vidéo (titre, auteur) et les miniatures directement dans le fichier téléchargé.
*   **Nommage de sortie personnalisé :** Personnalisez le modèle de nom de fichier de sortie.

## Prérequis

*   Python 3.6 ou supérieur
*   `yt-dlp`
*   `pytest` (pour l'exécution des tests)
*   `ffmpeg` (fortement recommandé pour la conversion de format et l'extraction audio)

## Installation

1.  Clonez ce dépôt ou téléchargez les fichiers sources.
2.  Installez les packages Python requis :

```bash
pip install -r requirements.txt
```

3.  Assurez-vous que `ffmpeg` est installé sur votre système.
    *   **Ubuntu/Debian :** `sudo apt install ffmpeg`
    *   **macOS :** `brew install ffmpeg`
    *   **Windows :** Téléchargez-le depuis le site officiel et ajoutez-le à votre variable d'environnement PATH.

## Utilisation

Exécutez le script `downloader.py` depuis le répertoire `src` :

```bash
python3 src/downloader.py [options] [URL]
```

### Options

*   `URL` : L'URL de la vidéo à télécharger (Facultatif si `--batch-file` est fourni).
*   `-a`, `--batch-file` : Fichier contenant les URL à télécharger, une par ligne.
*   `-f`, `--format` : Spécifiez le format vidéo souhaité (`mp4`, `mkv`, `best`). Par défaut, c'est `best`.
*   `-q`, `--quality` : Spécifiez la qualité vidéo souhaitée (`best`, `1080p`, `720p`, `480p`, `worst`). Par défaut, c'est `best`.
*   `--extract-audio` : Extrait uniquement l'audio (sauvegardé en MP3).
*   `--subtitles` : Télécharge les sous-titres s'ils sont disponibles.
*   `--no-playlist` : Télécharge uniquement la vidéo, en ignorant le reste de la playlist si l'URL en fait partie.
*   `--embed-metadata` : Intègre les métadonnées de la vidéo (titre, artiste, etc.) dans le fichier de sortie.
*   `--embed-thumbnail` : Intègre la miniature de la vidéo en tant que pochette.
*   `-o`, `--output` : Modèle de nom de fichier de sortie (par exemple, `%(title)s.%(ext)s`).

### Exemples

**Télécharger une vidéo avec les paramètres par défaut (meilleure qualité) :**
```bash
python3 src/downloader.py "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Télécharger une vidéo au format MP4 720p :**
```bash
python3 src/downloader.py -f mp4 -q 720p "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Extraire uniquement l'audio sous forme de MP3 :**
```bash
python3 src/downloader.py --extract-audio "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Télécharger une vidéo avec des sous-titres et l'enregistrer dans un répertoire spécifique :**
```bash
python3 src/downloader.py --subtitles -o "~/Downloads/%(title)s.%(ext)s" "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Télécharger une vidéo avec les métadonnées et la miniature intégrées :**
```bash
python3 src/downloader.py --embed-metadata --embed-thumbnail "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Télécharger plusieurs vidéos à partir d'un fichier texte (ex. `urls.txt`) :**
```bash
python3 src/downloader.py -a urls.txt
```

## Tests

Pour exécuter les tests automatisés, lancez `pytest` depuis le répertoire racine :

```bash
pytest tests/
```

## Avertissement

Cet outil est destiné uniquement au téléchargement de contenu accessible au public et non protégé. Il ne contourne pas la gestion des droits numériques (DRM) et ne télécharge pas de contenu protégé depuis des plateformes de streaming commerciales. Les utilisateurs sont responsables de s'assurer qu'ils ont le droit légal de télécharger et d'utiliser le contenu auquel ils accèdent avec cet outil.
