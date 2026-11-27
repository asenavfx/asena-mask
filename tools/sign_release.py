"""Release signing for Asena Mask updates.

  python tools/sign_release.py keygen                 make the key pair (once; refuses to overwrite) and print the public key
  python tools/sign_release.py sign release/version.json   write release/version.json.sig

The private key lives OUTSIDE the project: ../AsenaMask-keys/release_ed25519.key (next to the project folder) by default, or --key PATH / ASENA_SIGN_KEY.
Back it up: if it is lost, installed copies can never be updated again. Never edit version.json after signing."""
import base64
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from asenamask import RELEASE_PUBLIC_KEY, ed25519, release   # noqa: E402

DEFAULT_KEY = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "AsenaMask-keys", "release_ed25519.key")


def key_path(args):
    if "--key" in args:
        return args[args.index("--key") + 1]
    return os.environ.get("ASENA_SIGN_KEY") or DEFAULT_KEY


def main(args):
    if not args or args[0] not in ("keygen", "sign"):
        print(__doc__)
        return 2
    kp = key_path(args)
    if args[0] == "keygen":
        if os.path.exists(kp):
            print("Refusing: %s already exists (replacing it would lock out every installed copy)." % kp)
            return 1
        os.makedirs(os.path.dirname(os.path.abspath(kp)), exist_ok=True)
        seed = os.urandom(32)
        with open(kp, "x") as f:
            f.write(seed.hex() + "\n")
        print("Key written to %s" % kp)
        print('Public key (put in asenamask/__init__.py RELEASE_PUBLIC_KEY): "%s"' % ed25519.public_key(seed).hex())
        return 0
    target = args[1]
    with open(kp) as f:
        seed = bytes.fromhex(f.read().strip())
    with open(target, "rb") as f:
        raw = f.read()
    sig = base64.b64encode(ed25519.sign(seed, raw)).decode("ascii")
    if ed25519.public_key(seed).hex() != RELEASE_PUBLIC_KEY:
        print("Refusing: this key does not match RELEASE_PUBLIC_KEY in asenamask/__init__.py.")
        return 1
    release.check(raw, sig)          # same check the app and installer run; raises if version.json is malformed
    with open(target + ".sig", "w", newline="\n") as f:
        f.write(sig + "\n")
    print("Signed: %s.sig" % target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
