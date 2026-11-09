# Kajuen

Kajuen (le verger, en japonais) est le banc de test de Nashi. Il télécharge un build, lance un jeu avec le serveur de debug de Nashi, amène le jeu au même endroit à chaque fois grâce aux entrées manette injectées, mesure les frame times, prend des captures, garde le log, puis compare les variantes et les builds entre eux.

Il ne lit, ne copie et n'envoie jamais tes jeux, tes clés ou ton firmware : il donne seulement à `nashi.exe` le chemin du jeu que tu as configuré.

## Installation (Windows)

Il faut Python 3.10 ou plus récent (`winget install Python.Python.3.12`). Aucune autre dépendance.

```powershell
mkdir C:\Nashi
tar -xzf kajuen.tar.gz -C C:\Nashi
cd C:\Nashi\kajuen
python kajuen.py init
```

Ouvre ensuite `kajuen.json` et renseigne le chemin de tes jeux dans `games` (utilise des `/` ou des `\\` dans les chemins) :

```json
"games": {
  "oot": "D:/Switch2/The Legend of Zelda Ocarina of Time.nsp"
}
```

Puis récupère le dernier build de Nashi :

```powershell
python kajuen.py fetch
```

Par défaut c'est la version PGO (`windows-x86_64-pgo`). Pour la version standard : `python kajuen.py fetch --variant windows-x86_64`. Pour un build précis : `--tag build-12`. Si tu préfères un build que tu as compilé toi même, mets son dossier dans `"nashi"`.

Kajuen utilise le même dossier de données que Nashi (`%APPDATA%\eden`, ou le dossier `user` portable à côté de `nashi.exe`). Il faut donc que tes clés et ton firmware y soient déjà installés, comme pour jouer normalement.

## Premier test

```powershell
python kajuen.py run oot-titre
```

Nashi s'ouvre, démarre le jeu, attend l'écran titre, mesure 20 secondes, prend une capture et se ferme. Le résultat s'affiche et tout est rangé dans `runs\<date>-oot-titre-run\`.

## Les commandes

| Commande | Rôle |
|---|---|
| `python kajuen.py list` | liste les scénarios |
| `python kajuen.py builds` | liste les builds téléchargés et le build courant |
| `python kajuen.py fetch` | télécharge un build depuis les releases GitHub |
| `python kajuen.py run <scénario>` | lance toutes les variantes du scénario |
| `python kajuen.py run <scénario> --variant base --repeat 3` | une seule variante, trois passages moyennés |
| `python kajuen.py run <scénario> --build build-12-windows-x86_64-pgo` | sur un autre build |
| `python kajuen.py route <scénario>` | rejoue seulement la route et fait une capture de l'arrivée, pour régler la route |
| `python kajuen.py compare <run>` | compare les variantes d'un run |
| `python kajuen.py compare <run> <autre run>` | compare deux runs (par exemple deux builds) |
| `python kajuen.py history [<scénario>]` | évolution des fps build après build |
| `python kajuen.py mcp` | serveur MCP pour Claude (voir plus bas) |

Pour désigner un run, un morceau de son nom suffit, ou `last` pour le dernier.

## Écrire un scénario

Un scénario est un fichier JSON dans `scenarios\`. Le fichier `scenarios\_modele.json` explique chaque champ. En résumé :

- **game** : la clé du jeu dans `kajuen.json`.
- **boot** : délai maximum de démarrage, et `unlimited` pour lever la limite de vitesse pendant le démarrage et la route (c'est plus rapide, la limite revient avant la mesure).
- **route** : la suite d'actions rejouée à l'identique à chaque run. Chaque étape est soit une entrée manette tenue pendant un nombre d'images (`{"buttons": ["A"], "frames": 6}`, `{"left_stick": [0, 1], "frames": 180}`), soit une attente en secondes pour les chargements (`{"wait_s": 15}`), soit une capture de contrôle (`{"screenshot": "village"}`).
- **warmup_s** et **measure** : le temps d'attente sur place, puis la durée de mesure, le nombre de captures, et en option `profile_s` pour profiler les threads GPU.
- **variants** : chaque variante relance Nashi avec ses propres variables `EDEN_NX2_*` (`env`) ou des shaders désactivés (`reject_hashes`).

Comme Nashi ne sait pas faire de save states, une route part toujours de l'écran titre. Le plus fiable est de charger une sauvegarde posée juste à côté de l'endroit à mesurer. Avant de lancer quoi que ce soit, Kajuen fait une copie zip de tes sauvegardes une fois par jour dans `backups\`, parce qu'il ferme Nashi de force à la fin de chaque run.

Pour régler une route, enchaîne `python kajuen.py route <scénario>` et regarde les captures `route-*.png` et `fin-route.png` dans le dossier du run.

## Ce que contient un run

```
runs\20261109-2130-oot-plaine-run\
  resume.md          le tableau des résultats
  run.json           tous les chiffres
  base\
    result.json      fps, 1 % low, p50, p99, saccades, erreurs du log
    capture-1.png    captures après la mesure
    route-*.png      captures de contrôle de la route
    eden_log.txt     le log complet de la session
    profil.json      profil des threads, si demandé
    debug\           fichiers du serveur de debug
```

`history.csv` garde une ligne par variante et par run, pour suivre les fps d'un build à l'autre.

## Brancher Kajuen sur Claude

Kajuen est aussi un serveur MCP. Une fois branché dans Claude Desktop, Claude peut télécharger un build, lancer les scénarios, lire les résultats et les captures, écrire de nouveaux scénarios, et interroger en direct un jeu déjà lancé (outils `live_*` : capture, frame times, log, injection de manette, shaders).

Dans Claude Desktop, ouvre Paramètres, Développeur, Modifier la config, et ajoute :

```json
{
  "mcpServers": {
    "kajuen": {
      "command": "python",
      "args": ["C:\\Nashi\\kajuen\\kajuen.py", "mcp"]
    }
  }
}
```

Redémarre Claude Desktop. Un run complet dure plusieurs minutes : garde Claude Desktop ouvert pendant ce temps.
