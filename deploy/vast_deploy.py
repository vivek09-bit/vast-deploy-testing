#!/usr/bin/env python3
"""Deploy the IndicF5 server to Vast.ai using the `vastai` CLI.

Usage (PowerShell: set $env:HF_TOKEN, $env:API_KEY, $env:REF_TEXT first):
    python deploy/vast_deploy.py up --package-spec "git+https://github.com/YOU/REPO.git" --ref-audio /root/ref.wav
    python deploy/vast_deploy.py status INSTANCE_ID
    python deploy/vast_deploy.py down INSTANCE_ID
"""
import argparse
import json
import os
import subprocess
import sys

IMAGE = "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime"
PORT = 8000
GPU_CHOICES = ["RTX_4090", "RTX_3090", "RTX_A5000", "RTX_A4000"]


def vast(*args):
    out = subprocess.run(["vastai", *args, "--raw"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"vastai {' '.join(args)} failed:\n{out.stderr or out.stdout}")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return out.stdout


def find_offer(max_price):
    for gpu in GPU_CHOICES:
        query = (
            f"gpu_name={gpu} num_gpus=1 reliability>0.98 disk_space>=40 "
            f"inet_down>200 dph<={max_price} rentable=true"
        )
        offers = vast("search", "offers", query, "-o", "dph")
        if offers:
            return offers[0]
    sys.exit("No matching offer found. Raise --max-price or relax GPU_CHOICES.")


def cmd_up(a):
    for var in ("HF_TOKEN", "API_KEY", "REF_TEXT"):
        if not os.environ.get(var):
            sys.exit(f"Set the {var} environment variable first.")

    offer = find_offer(a.max_price)
    print(f"Renting offer {offer['id']}: {offer['gpu_name']} @ ${offer['dph_total']:.3f}/hr")

    onstart = (
        "apt-get update && apt-get install -y ffmpeg libsndfile1 git && "
        "pip install -q git+https://github.com/ai4bharat/IndicF5.git "
        f"'{a.package_spec}' && "
        "nohup indicf5-server > /root/server.log 2>&1 &"
    )
    env = (
        f"-p {PORT}:{PORT} "
        f"-e HF_TOKEN={os.environ['HF_TOKEN']} "
        f"-e API_KEY={os.environ['API_KEY']} "
        f"-e REF_AUDIO_PATH={a.ref_audio} "
        f"-e 'REF_TEXT={os.environ['REF_TEXT']}'"
    )
    result = vast(
        "create", "instance", str(offer["id"]),
        "--image", IMAGE,
        "--disk", str(a.disk),
        "--env", env,
        "--onstart-cmd", onstart,
        "--ssh", "--direct",
    )
    print(result)
    print("Instance starting. Run `status <INSTANCE_ID>` in a minute or two.")


def cmd_status(a):
    info = vast("show", "instance", str(a.instance_id))
    print(f"State: {info.get('actual_status')}  Cost: ${info.get('dph_total', 0):.3f}/hr")
    ip = info.get("public_ipaddr")
    mapping = (info.get("ports") or {}).get(f"{PORT}/tcp")
    if ip and mapping:
        print(f"API:    http://{ip}:{mapping[0]['HostPort']}   (health: /health, POST /tts)")
    print(f"SSH:    ssh -p {info.get('ssh_port')} root@{info.get('ssh_host')}")
    print("Logs:   tail -f /root/server.log (on the instance)")


def cmd_down(a):
    print(vast("destroy", "instance", str(a.instance_id)))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("up", help="rent a GPU and start the server")
    up.add_argument("--package-spec", required=True)
    up.add_argument("--ref-audio", required=True)
    up.add_argument("--max-price", type=float, default=0.50, help="max $/hr")
    up.add_argument("--disk", type=int, default=40, help="disk GB")
    up.set_defaults(fn=cmd_up)

    st = sub.add_parser("status", help="show state, URL and SSH command")
    st.add_argument("instance_id", type=int)
    st.set_defaults(fn=cmd_status)

    dn = sub.add_parser("down", help="destroy the instance (stops billing)")
    dn.add_argument("instance_id", type=int)
    dn.set_defaults(fn=cmd_down)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()