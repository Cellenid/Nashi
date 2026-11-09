#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Kajuen, the Nashi test bench.

Downloads a Nashi build, boots a game with the debug server on, walks to a fixed spot with
injected input, measures frame times, takes screenshots, keeps the log, and compares variants
(environment switches, rejected shaders, builds). Results land in runs/ as JSON, PNG and
Markdown, and in history.csv so a build can be compared with the last one.

  python kajuen.py init                      write kajuen.json next to this script
  python kajuen.py fetch [--tag build-12]    download a release build from Cellenid/Nashi
  python kajuen.py builds                    list downloaded builds
  python kajuen.py list                      list scenarios
  python kajuen.py run <scenario> [...]      run a scenario (every variant, or --variant)
  python kajuen.py route <scenario>          boot and replay the route only, then screenshot
  python kajuen.py compare <run> [<run>]     compare the variants of one run, or two runs
  python kajuen.py history [<scenario>]      fps per build over time
  python kajuen.py mcp                       stdio MCP server (Kajuen tools plus live debug tools)

Standard library only (Python 3.10 or newer). Game files, keys and firmware are never read,
copied or uploaded: Kajuen only passes the game path you configured to nashi.exe.
"""

import argparse
import base64
import csv
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
for candidate in (HERE, os.path.join(HERE, "..", "nx2")):
    if os.path.isfile(os.path.join(candidate, "debug_mcp.py")):
        sys.path.insert(0, os.path.abspath(candidate))
        break
import debug_mcp  # noqa: E402  (Nashi's debug server client, tools/nx2/debug_mcp.py)

VERSION = "1"
REPO = "Cellenid/Nashi"
DEBUG_ADDRESS = "127.0.0.1:6545"
CONFIG_PATH = os.path.join(HERE, "kajuen.json")
IS_WINDOWS = os.name == "nt"

DEFAULT_CONFIG = {
    "repo": REPO,
    "variant": "windows-x86_64-pgo" if IS_WINDOWS else "linux-x86_64",
    "nashi": "",
    "user": 0,
    "debug_address": DEBUG_ADDRESS,
    "data_dir": "",
    "backup_saves": True,
    "games": {
        "oot": "C:/Jeux/Switch2/Ocarina of Time.nsp",
    },
}


class KajuenError(Exception):
    pass


def say(message):
    print(message, file=sys.stderr, flush=True)


def now_stamp():
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


# Configuration and paths ------------------------------------------------------------------------

def load_config():
    if not os.path.isfile(CONFIG_PATH):
        raise KajuenError("kajuen.json introuvable : lance d'abord « python kajuen.py init ».")
    with open(CONFIG_PATH, encoding="utf-8") as file:
        config = {**DEFAULT_CONFIG, **json.load(file)}
    return config


def path_in(*parts):
    path = os.path.join(HERE, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def data_dir(config):
    """Nashi's user folder: portable 'user' next to the exe, else %APPDATA%/eden (Eden's name)."""
    if config.get("data_dir"):
        return config["data_dir"]
    exe = resolve_exe(config, None)
    portable = os.path.join(os.path.dirname(exe), "user")
    if os.path.isdir(portable):
        return portable
    if IS_WINDOWS:
        return os.path.join(os.environ.get("APPDATA", ""), "eden")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "eden")


def builds_dir():
    return os.path.join(HERE, "builds")


def resolve_exe(config, build):
    """The nashi executable for a build name, a path, or the configured / current build."""
    name = "nashi.exe" if IS_WINDOWS else "nashi"
    candidates = []
    if build:
        candidates += [build, os.path.join(builds_dir(), build)]
    elif config.get("nashi"):
        candidates.append(config["nashi"])
    else:
        current = os.path.join(builds_dir(), "current.txt")
        if os.path.isfile(current):
            with open(current, encoding="utf-8") as file:
                candidates.append(os.path.join(builds_dir(), file.read().strip()))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
        found = os.path.join(candidate, name)
        if os.path.isfile(found):
            return os.path.abspath(found)
        for root, _, files in os.walk(candidate):
            if name in files:
                return os.path.abspath(os.path.join(root, name))
    raise KajuenError("aucun build de Nashi trouvé : lance « python kajuen.py fetch » ou "
                      "renseigne \"nashi\" dans kajuen.json.")


def build_label(exe):
    rel = os.path.relpath(exe, builds_dir())
    return rel.split(os.sep)[0] if not rel.startswith("..") else os.path.basename(os.path.dirname(exe))


# Builds -----------------------------------------------------------------------------------------

def github_json(url):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "Kajuen"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch(config, tag=None, variant=None):
    variant = variant or config["variant"]
    releases = github_json(f"https://api.github.com/repos/{config['repo']}/releases?per_page=20")
    if tag:
        releases = [release for release in releases if release["tag_name"] == tag]
    asset_name = f"nashi-{variant}.zip"
    for release in releases:
        asset = next((a for a in release.get("assets", []) if a["name"] == asset_name), None)
        if asset is None:
            continue
        name = f"{release['tag_name']}-{variant}"
        target = os.path.join(builds_dir(), name)
        if not os.path.isdir(target):
            archive = path_in("builds", f"{name}.zip")
            say(f"Téléchargement de {asset_name} ({asset['size'] // (1 << 20)} Mo) depuis "
                f"{release['tag_name']}...")
            request = urllib.request.Request(asset["browser_download_url"],
                                             headers={"User-Agent": "Kajuen"})
            with urllib.request.urlopen(request, timeout=600) as response, \
                    open(archive, "wb") as file:
                shutil.copyfileobj(response, file)
            with zipfile.ZipFile(archive) as zip_file:
                zip_file.extractall(target)
            os.remove(archive)
        with open(path_in("builds", "current.txt"), "w", encoding="utf-8") as file:
            file.write(name)
        commit = release.get("target_commitish", "")
        return {"build": name, "path": target, "release": release["html_url"], "commit": commit}
    wanted = f" {tag}" if tag else ""
    raise KajuenError(f"aucune release{wanted} de {config['repo']} ne contient {asset_name}.")


def list_builds():
    current = ""
    current_file = os.path.join(builds_dir(), "current.txt")
    if os.path.isfile(current_file):
        with open(current_file, encoding="utf-8") as file:
            current = file.read().strip()
    names = sorted(entry for entry in os.listdir(builds_dir())
                   if os.path.isdir(os.path.join(builds_dir(), entry))) \
        if os.path.isdir(builds_dir()) else []
    return {"current": current, "builds": names}


# Scenarios --------------------------------------------------------------------------------------

def scenarios_dir():
    return os.path.join(HERE, "scenarios")


def load_scenario(name):
    path = name if os.path.isfile(name) else os.path.join(scenarios_dir(), f"{name}.json")
    if not os.path.isfile(path):
        raise KajuenError(f"scénario introuvable : {name}")
    with open(path, encoding="utf-8") as file:
        scenario = json.load(file)
    scenario.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    scenario.setdefault("boot", {})
    scenario.setdefault("route", [])
    scenario.setdefault("warmup_s", 10)
    scenario.setdefault("measure", {})
    scenario.setdefault("variants", [{"name": "base"}])
    return scenario


def list_scenarios():
    out = []
    if os.path.isdir(scenarios_dir()):
        for entry in sorted(os.listdir(scenarios_dir())):
            if entry.endswith(".json") and not entry.startswith("_"):
                scenario = load_scenario(os.path.join(scenarios_dir(), entry))
                out.append({"name": scenario["name"], "game": scenario.get("game"),
                            "description": scenario.get("description", ""),
                            "variants": [v["name"] for v in scenario["variants"]]})
    return out


# Save backups -----------------------------------------------------------------------------------

def backup_saves(config):
    """Zips nand/user/save once a day before Kajuen starts killing the emulator."""
    if not config.get("backup_saves", True):
        return None
    save_dir = os.path.join(data_dir(config), "nand", "user", "save")
    if not os.path.isdir(save_dir):
        return None
    today = dt.date.today().strftime("%Y%m%d")
    folder = os.path.join(HERE, "backups")
    os.makedirs(folder, exist_ok=True)
    existing = sorted(f for f in os.listdir(folder) if f.startswith("saves-"))
    if any(f.startswith(f"saves-{today}") for f in existing):
        return None
    base = os.path.join(folder, f"saves-{today}-{dt.datetime.now().strftime('%H%M%S')}")
    archive = shutil.make_archive(base, "zip", save_dir)
    for old in existing[:-9]:
        os.remove(os.path.join(folder, old))
    say(f"Sauvegardes copiées dans {archive}")
    return archive


# One emulator session ---------------------------------------------------------------------------

class Session:
    """Starts nashi.exe on a game with the debug server, and always stops it."""

    def __init__(self, config, exe, game_path, env, out_dir):
        self.config = config
        self.exe = exe
        self.game_path = game_path
        self.env = env
        self.out_dir = out_dir
        self.process = None
        self.emulator = debug_mcp.Emulator(config.get("debug_address", DEBUG_ADDRESS))
        self.adapter = debug_mcp.Adapter(self.emulator)
        self.log_start = 0

    def __enter__(self):
        if not os.path.isfile(self.game_path):
            raise KajuenError(f"jeu introuvable : {self.game_path}")
        env = dict(os.environ)
        env.update({key: str(value) for key, value in self.env.items()})
        env["EDEN_NX2_DEBUG_SERVER"] = self.config.get("debug_address", DEBUG_ADDRESS)
        env["EDEN_NX2_DEBUG_DIR"] = os.path.join(self.out_dir, "debug")
        os.makedirs(env["EDEN_NX2_DEBUG_DIR"], exist_ok=True)
        args = [self.exe, "-u", str(self.config.get("user", 0)), "-g", self.game_path]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
        self.stdout = open(os.path.join(self.out_dir, "stdout.txt"), "wb")
        self.process = subprocess.Popen(args, env=env, cwd=os.path.dirname(self.exe),
                                        stdout=self.stdout, stderr=subprocess.STDOUT,
                                        creationflags=flags,
                                        start_new_session=not IS_WINDOWS)
        return self

    def __exit__(self, *exc):
        self.emulator.close()
        self.stop()
        self.stdout.close()
        self.copy_log()
        return False

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def stop(self):
        if not self.alive():
            return
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                           capture_output=True)
        else:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except OSError:
                self.process.kill()
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass

    def copy_log(self):
        log = os.path.join(data_dir(self.config), "log", "eden_log.txt")
        if os.path.isfile(log):
            try:
                shutil.copy2(log, os.path.join(self.out_dir, "eden_log.txt"))
            except OSError:
                pass

    def call(self, method, params=None, timeout=None):
        params = params or {}
        if not self.alive():
            raise KajuenError(f"Nashi s'est arrêté (code {self.process.returncode}) pendant "
                              f"« {method} »")
        if timeout is None:
            timeout = debug_mcp.default_timeout(method, params) + 30
        try:
            return self.emulator.call(method, params, timeout)
        except debug_mcp.EmulatorError as error:
            if not self.alive():
                raise KajuenError(f"Nashi s'est arrêté (code {self.process.returncode}) pendant "
                                  f"« {method} »") from error
            raise KajuenError(f"{method} : {error}") from error

    def wait_boot(self, max_wait_s, min_presents=60):
        """Waits until the debug server answers and the game presents frames."""
        deadline = time.monotonic() + max_wait_s
        last_error = "le serveur de debug ne répond pas"
        while time.monotonic() < deadline:
            if not self.alive():
                raise KajuenError(f"Nashi s'est arrêté au démarrage (code "
                                  f"{self.process.returncode}), voir eden_log.txt")
            try:
                status = self.emulator.call("status", {}, 10)
                if status.get("presents", 0) >= min_presents and not status.get("paused"):
                    return status
                last_error = f"{status.get('presents', 0)} images présentées"
            except debug_mcp.EmulatorError as error:
                last_error = str(error)
                self.emulator.close()
            time.sleep(2)
        raise KajuenError(f"le jeu n'a pas démarré en {max_wait_s} s ({last_error})")

    def screenshot(self, name):
        result, png = self.adapter.run("screenshot", {})
        path = os.path.join(self.out_dir, f"{name}.png")
        if png:
            with open(path, "wb") as file:
                file.write(png)
            return path
        return None

    def errors_in_log(self):
        try:
            lines = self.call("log_tail", {"limit": 2000})["lines"]
        except KajuenError:
            return []
        if isinstance(lines, str):
            lines = lines.splitlines()
        keep = [line for line in lines if "<Error>" in line or "<Critical>" in line
                or "[Error]" in line or "[Critical]" in line]
        return keep[-50:]


def run_route(session, route, label="route"):
    """Replays the route in chunks the debug server accepts (1000 steps, 36000 frames)."""
    chunk, frames = [], 0
    for step in route + [None]:
        # Waits and screenshots happen between input calls, so pending input goes first.
        flush = (step is None or "wait_s" in step or "screenshot" in step or len(chunk) == 1000
                 or frames + step.get("frames", 0) > 36000)
        if flush and chunk:
            session.call("input_sequence", {"steps": chunk})
            chunk, frames = [], 0
        if step is None:
            break
        if "wait_s" in step:
            time.sleep(float(step["wait_s"]))
            continue
        if "screenshot" in step:
            session.screenshot(f"{label}-{step['screenshot']}")
            continue
        step = {k: v for k, v in step.items() if k in ("buttons", "left_stick", "right_stick",
                                                       "frames")}
        chunk.append(step)
        frames += step["frames"]


def summarize_frames(frames):
    keys = ("fps", "mean_ms", "p50_ms", "p90_ms", "p99_ms", "max_ms", "stutters", "frames",
            "vsync_buckets")
    summary = {key: (round(frames[key], 2) if isinstance(frames.get(key), float) else frames.get(key))
               for key in keys}
    p99 = frames.get("p99_ms") or 0
    summary["low1_fps"] = round(1000.0 / p99, 1) if p99 else 0.0
    return summary


def run_variant(config, scenario, variant, exe, game_path, out_dir, route_only=False):
    os.makedirs(out_dir, exist_ok=True)
    env = {**scenario.get("env", {}), **variant.get("env", {})}
    boot = scenario["boot"]
    measure = scenario["measure"]
    result = {"variant": variant["name"], "build": build_label(exe), "env": env, "ok": False,
              "started": dt.datetime.now().isoformat(timespec="seconds")}
    try:
        with Session(config, exe, game_path, env, out_dir) as session:
            status = session.wait_boot(int(boot.get("max_wait_s", 240)),
                                       int(boot.get("min_presents", 60)))
            result["title"] = status.get("title")
            result["program_id"] = status.get("program_id")
            result["nashi_build"] = status.get("build")
            unlimited = bool(boot.get("unlimited", False))
            if unlimited:
                session.call("speed_limit", {"on": False})
            if boot.get("settle_s"):
                time.sleep(float(boot["settle_s"]))
            run_route(session, scenario["route"])
            if unlimited:
                session.call("speed_limit", {"on": True})
            if variant.get("reject_hashes"):
                session.call("reject_shaders", {"hashes": variant["reject_hashes"],
                                                "reject": True})
            if route_only:
                result["screenshots"] = [session.screenshot("fin-route")]
                result["ok"] = True
                return result
            time.sleep(float(scenario.get("warmup_s", 10)))
            shots = []
            count = int(measure.get("screenshots", 1))
            seconds = float(measure.get("seconds", 30))
            frames = session.call("frame_times", {"seconds": seconds,
                                                  "refresh_hz": measure.get("refresh_hz", 60)})
            result["frames"] = summarize_frames(frames)
            for index in range(count):
                shots.append(session.screenshot(f"capture-{index + 1}"))
                if index + 1 < count:
                    time.sleep(1)
            result["screenshots"] = [s for s in shots if s]
            if measure.get("profile_s"):
                sample = session.call("sample", {"seconds": int(measure["profile_s"])})
                with open(os.path.join(out_dir, "profil.json"), "w", encoding="utf-8") as file:
                    json.dump(sample, file, indent=1)
                result["profile"] = "profil.json"
            result["log_errors"] = session.errors_in_log()
            result["ok"] = True
    except KajuenError as error:
        result["error"] = str(error)
    finally:
        result["finished"] = dt.datetime.now().isoformat(timespec="seconds")
        with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as file:
            json.dump(result, file, indent=1, ensure_ascii=False)
    return result


def run_scenario(config, name, build=None, variants=None, repeat=None, route_only=False):
    scenario = load_scenario(name)
    exe = resolve_exe(config, build)
    game = scenario.get("game")
    game_path = config["games"].get(game, game) if game else None
    if not game_path:
        raise KajuenError(f"le scénario {scenario['name']} ne précise pas de jeu")
    chosen = scenario["variants"]
    if variants:
        chosen = [v for v in chosen if v["name"] in variants]
        if not chosen:
            raise KajuenError(f"aucune variante {variants} dans {scenario['name']}")
    if route_only:
        chosen = chosen[:1]
    repeat = 1 if route_only else int(repeat or scenario.get("repeat", 1))
    backup_saves(config)
    kind = "route" if route_only else "run"
    run_dir = path_in("runs", f"{now_stamp()}-{scenario['name']}-{kind}", "x")[:-2]
    results = []
    for round_index in range(repeat):
        for variant in chosen:
            folder = variant["name"] if repeat == 1 else f"{variant['name']}-{round_index + 1}"
            say(f"[{scenario['name']}] {folder} sur {build_label(exe)}...")
            result = run_variant(config, scenario, variant, exe, game_path,
                                 os.path.join(run_dir, folder), route_only)
            say(describe(result))
            results.append(result)
    report = {"scenario": scenario["name"], "build": build_label(exe), "dir": run_dir,
              "results": results}
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as file:
        json.dump(report, file, indent=1, ensure_ascii=False)
    with open(os.path.join(run_dir, "resume.md"), "w", encoding="utf-8") as file:
        file.write(markdown_report(report))
    if not route_only:
        append_history(report)
    return report


def describe(result):
    if not result.get("ok"):
        return f"  échec : {result.get('error')}"
    frames = result.get("frames")
    if not frames:
        return "  ok"
    return (f"  {frames['fps']:.1f} fps, 1 % low {frames['low1_fps']:.1f} fps, p99 "
            f"{frames['p99_ms']:.1f} ms, {frames['stutters']} saccades")


# Reports ----------------------------------------------------------------------------------------

def merged(results):
    """Averages repeated rounds of the same variant."""
    groups = {}
    for result in results:
        groups.setdefault(result["variant"], []).append(result)
    rows = []
    for variant, items in groups.items():
        good = [r["frames"] for r in items if r.get("ok") and r.get("frames")]
        row = {"variant": variant, "runs": len(items), "ok": len(good),
               "errors": [r.get("error") for r in items if not r.get("ok")]}
        if good:
            for key in ("fps", "low1_fps", "p50_ms", "p99_ms", "stutters"):
                row[key] = round(sum(g[key] for g in good) / len(good), 2)
        rows.append(row)
    return rows


def table(rows, base=None):
    lines = ["| Variante | fps | 1 % low | p50 ms | p99 ms | saccades | réussis |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        if "fps" not in row:
            lines.append(f"| {row['variant']} | échec | | | | | 0/{row['runs']} |")
            continue
        delta = ""
        if base and "fps" in base and base is not row and base["fps"]:
            delta = f" ({(row['fps'] / base['fps'] - 1) * 100:+.1f} %)"
        lines.append(f"| {row['variant']} | {row['fps']:.1f}{delta} | {row['low1_fps']:.1f} | "
                     f"{row['p50_ms']:.1f} | {row['p99_ms']:.1f} | {row['stutters']:.0f} | "
                     f"{row['ok']}/{row['runs']} |")
    return "\n".join(lines)


def markdown_report(report):
    rows = merged(report["results"])
    out = [f"# {report['scenario']}", "", f"Build : {report['build']}", ""]
    if any("fps" in row for row in rows):
        base = next((row for row in rows if "fps" in row), None)
        out += [table(rows, base), ""]
    for result in report["results"]:
        if not result.get("ok"):
            out.append(f"Échec de {result['variant']} : {result.get('error')}")
        elif result.get("log_errors"):
            count = len(result["log_errors"])
            out.append(f"{result['variant']} : {count} erreur{'s' if count > 1 else ''} dans le log")
    return "\n".join(out).rstrip() + "\n"


def append_history(report):
    path = os.path.join(HERE, "history.csv")
    fresh = not os.path.isfile(path)
    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if fresh:
            writer.writerow(["date", "scenario", "variant", "build", "fps", "low1_fps", "p99_ms",
                             "stutters", "ok", "run"])
        for result in report["results"]:
            frames = result.get("frames") or {}
            writer.writerow([result.get("started"), report["scenario"], result["variant"],
                             result["build"], frames.get("fps", ""), frames.get("low1_fps", ""),
                             frames.get("p99_ms", ""), frames.get("stutters", ""),
                             int(bool(result.get("ok"))), os.path.basename(report["dir"])])


def find_run(name):
    if os.path.isdir(name):
        return name
    runs = os.path.join(HERE, "runs")
    matches = sorted(d for d in os.listdir(runs) if name in d) if os.path.isdir(runs) else []
    if name == "last" and os.path.isdir(runs):
        matches = sorted(d for d in os.listdir(runs) if d.endswith("-run"))[-1:]
    if not matches:
        raise KajuenError(f"aucun run ne correspond à {name}")
    return os.path.join(runs, matches[-1])


def load_run(name):
    with open(os.path.join(find_run(name), "run.json"), encoding="utf-8") as file:
        return json.load(file)


def compare(first, second=None):
    a = load_run(first)
    if second is None:
        rows = merged(a["results"])
        base = next((row for row in rows if "fps" in row), None)
        return f"# {a['scenario']} ({a['build']})\n\n{table(rows, base)}\n"
    b = load_run(second)
    rows_a = {row["variant"]: row for row in merged(a["results"])}
    rows_b = {row["variant"]: row for row in merged(b["results"])}
    lines = [f"# {a['scenario']} : {a['build']} → {b['build']}", "",
             "| Variante | fps avant | fps après | écart | 1 % low avant | 1 % low après |",
             "|---|---|---|---|---|---|"]
    for variant in sorted(set(rows_a) | set(rows_b)):
        ra, rb = rows_a.get(variant, {}), rows_b.get(variant, {})
        fa, fb = ra.get("fps"), rb.get("fps")
        delta = f"{(fb / fa - 1) * 100:+.1f} %" if fa and fb else ""
        def fmt(row, key):
            if not row:
                return "absent"
            value = row.get(key)
            return f"{value:.1f}" if isinstance(value, (int, float)) else "échec"
        lines.append(f"| {variant} | {fmt(ra, 'fps')} | {fmt(rb, 'fps')} | {delta} | "
                     f"{fmt(ra, 'low1_fps')} | {fmt(rb, 'low1_fps')} |")
    return "\n".join(lines) + "\n"


def history(scenario=None):
    path = os.path.join(HERE, "history.csv")
    if not os.path.isfile(path):
        return "Aucun historique pour l'instant.\n"
    with open(path, newline="", encoding="utf-8") as file:
        rows = [r for r in csv.DictReader(file) if not scenario or r["scenario"] == scenario]
    lines = ["| Date | Scénario | Variante | Build | fps | 1 % low | p99 ms |",
             "|---|---|---|---|---|---|---|"]
    for row in rows[-40:]:
        lines.append(f"| {row['date']} | {row['scenario']} | {row['variant']} | {row['build']} | "
                     f"{row['fps'] or 'échec'} | {row['low1_fps']} | {row['p99_ms']} |")
    return "\n".join(lines) + "\n"


# MCP server -------------------------------------------------------------------------------------

KAJUEN_TOOLS = [
    {"name": "kajuen_list", "description": "Lists Kajuen scenarios and downloaded Nashi builds.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "kajuen_fetch",
     "description": "Downloads a Nashi release build from GitHub (latest, or a given tag such as "
                    "build-12) and makes it the current build.",
     "inputSchema": {"type": "object", "properties": {
         "tag": {"type": "string"}, "variant": {"type": "string"}}}},
    {"name": "kajuen_run",
     "description": "Runs a scenario: boots the game in Nashi with the debug server, replays the "
                    "route, measures frame times, takes screenshots, then closes Nashi. Returns "
                    "the Markdown summary and the first screenshot of each variant. Takes minutes.",
     "inputSchema": {"type": "object", "properties": {
         "scenario": {"type": "string"}, "build": {"type": "string"},
         "variants": {"type": "array", "items": {"type": "string"}},
         "repeat": {"type": "integer", "minimum": 1, "maximum": 5}},
         "required": ["scenario"]}},
    {"name": "kajuen_route",
     "description": "Boots the game and replays only the scenario's route, then returns a "
                    "screenshot of where it ended, to tune the route.",
     "inputSchema": {"type": "object", "properties": {
         "scenario": {"type": "string"}, "build": {"type": "string"}},
         "required": ["scenario"]}},
    {"name": "kajuen_compare",
     "description": "Compares the variants of one run, or the same scenario across two runs "
                    "(run folder names, substrings, or 'last').",
     "inputSchema": {"type": "object", "properties": {
         "run": {"type": "string"}, "other": {"type": "string"}}, "required": ["run"]}},
    {"name": "kajuen_history", "description": "fps per build over time for a scenario.",
     "inputSchema": {"type": "object", "properties": {"scenario": {"type": "string"}}}},
    {"name": "kajuen_scenario_write",
     "description": "Creates or replaces a scenario file (JSON object; see scenarios/_modele.json).",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string"}, "scenario": {"type": "object"}},
         "required": ["name", "scenario"]}},
]


def image_content(path):
    with open(path, "rb") as file:
        return {"type": "image", "data": base64.b64encode(file.read()).decode(),
                "mimeType": "image/png"}


class KajuenMcp(debug_mcp.Adapter):
    """Kajuen's tools, plus the live debug tools (prefixed live_) for a game already running."""

    def __init__(self, config):
        super().__init__(debug_mcp.Emulator(config.get("debug_address", DEBUG_ADDRESS)))
        self.config = config

    def call_tool(self, name, arguments):
        if name.startswith("live_"):
            return super().call_tool(name[5:], arguments)
        try:
            if name == "kajuen_list":
                return [debug_mcp.text({"scenarios": list_scenarios(), **list_builds()})]
            if name == "kajuen_fetch":
                return [debug_mcp.text(fetch(self.config, arguments.get("tag"),
                                             arguments.get("variant")))]
            if name in ("kajuen_run", "kajuen_route"):
                report = run_scenario(self.config, arguments["scenario"], arguments.get("build"),
                                      arguments.get("variants"), arguments.get("repeat"),
                                      route_only=name == "kajuen_route")
                content = [debug_mcp.text(markdown_report(report) + f"\nDossier : {report['dir']}")]
                for result in report["results"]:
                    shots = result.get("screenshots") or []
                    if shots:
                        content.append(debug_mcp.text(f"Capture de {result['variant']} :"))
                        content.append(image_content(shots[0]))
                return content
            if name == "kajuen_compare":
                return [debug_mcp.text(compare(arguments["run"], arguments.get("other")))]
            if name == "kajuen_history":
                return [debug_mcp.text(history(arguments.get("scenario")))]
            if name == "kajuen_scenario_write":
                safe = "".join(c for c in arguments["name"] if c.isalnum() or c in "-_")
                if not safe:
                    raise KajuenError("nom de scénario invalide")
                path = path_in("scenarios", f"{safe}.json")
                with open(path, "w", encoding="utf-8") as file:
                    json.dump(arguments["scenario"], file, indent=2, ensure_ascii=False)
                load_scenario(safe)
                return [debug_mcp.text(f"Scénario écrit : {path}")]
        except KajuenError as error:
            raise debug_mcp.EmulatorError(str(error)) from error
        raise debug_mcp.EmulatorError(f"outil inconnu : {name}")

    def handle(self, message):
        if message.get("method") == "tools/list" and "id" in message:
            live = [{**tool, "name": f"live_{tool['name']}",
                     "description": "Live, on a game already running with the debug server: "
                                    + tool["description"]} for tool in debug_mcp.TOOLS]
            return {"jsonrpc": "2.0", "id": message["id"],
                    "result": {"tools": KAJUEN_TOOLS + live}}
        reply = super().handle(message)
        if reply and message.get("method") == "initialize":
            reply["result"]["serverInfo"] = {"name": "kajuen", "version": VERSION}
        return reply


# Command line -----------------------------------------------------------------------------------

def init():
    if os.path.isfile(CONFIG_PATH):
        return f"kajuen.json existe déjà : {CONFIG_PATH}"
    with open(CONFIG_PATH, "w", encoding="utf-8") as file:
        json.dump(DEFAULT_CONFIG, file, indent=2, ensure_ascii=False)
    os.makedirs(scenarios_dir(), exist_ok=True)
    return (f"kajuen.json créé : {CONFIG_PATH}\nRenseigne le chemin de tes jeux dans \"games\", "
            f"puis lance « python kajuen.py fetch ».")


def main(argv=None):
    if IS_WINDOWS:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass
    parser = argparse.ArgumentParser(prog="kajuen", description="Banc de test de Nashi.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    p = sub.add_parser("fetch")
    p.add_argument("--tag")
    p.add_argument("--variant")
    sub.add_parser("builds")
    sub.add_parser("list")
    for command in ("run", "route"):
        p = sub.add_parser(command)
        p.add_argument("scenario")
        p.add_argument("--build")
        if command == "run":
            p.add_argument("--variant", action="append")
            p.add_argument("--repeat", type=int)
    p = sub.add_parser("compare")
    p.add_argument("run")
    p.add_argument("other", nargs="?")
    p = sub.add_parser("history")
    p.add_argument("scenario", nargs="?")
    sub.add_parser("mcp")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            print(init())
            return 0
        config = load_config()
        if args.command == "fetch":
            print(json.dumps(fetch(config, args.tag, args.variant), indent=1))
        elif args.command == "builds":
            print(json.dumps(list_builds(), indent=1))
        elif args.command == "list":
            print(json.dumps(list_scenarios(), indent=1, ensure_ascii=False))
        elif args.command in ("run", "route"):
            report = run_scenario(config, args.scenario, args.build,
                                  getattr(args, "variant", None), getattr(args, "repeat", None),
                                  route_only=args.command == "route")
            print(markdown_report(report))
            print(f"Dossier : {report['dir']}")
            return 0 if all(r.get("ok") for r in report["results"]) else 1
        elif args.command == "compare":
            print(compare(args.run, args.other))
        elif args.command == "history":
            print(history(args.scenario))
        elif args.command == "mcp":
            debug_mcp.serve(KajuenMcp(config), sys.stdin, sys.stdout)
    except KajuenError as error:
        say(f"Erreur : {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
