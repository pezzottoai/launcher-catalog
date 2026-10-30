#!/usr/bin/env python3
"""Sign and verify index.json in minisign format.

The launcher ships the catalog public key and refuses an index.json whose signature does
not verify, so a mirror, a CDN or a hijacked DNS entry cannot feed it a different catalog.
Signatures are standard minisign (https://jedisct1.github.io/minisign/), so anyone can
check them with the minisign tool as well:

  minisign -Vm index.json -p keys/pezzotto-launcher-catalog.pub

Usage:
  scripts/sign_index.py pubkey  --key KEY.pem                 # print the minisign public key file
  scripts/sign_index.py sign    --key KEY.pem [FILE]          # write FILE.minisig
  scripts/sign_index.py verify  --pub  KEY.pub [FILE]         # exit 0 when FILE.minisig is valid

The private key is an Ed25519 key in PEM form (openssl genpkey -algorithm ed25519); it can
also be passed in the CATALOG_SIGNING_KEY environment variable, which is what CI does.
Only the Python standard library is needed: Ed25519 is implemented below, straight from
RFC 8032 section 6 (slow, but we sign one small hash).
"""
import argparse
import base64
import hashlib
import os
import pathlib
import sys
import time

SIG_ALG_PREHASHED = b"ED"   # Ed25519 over Blake2b-512 of the file (minisign default since 0.8)
SIG_ALG_LEGACY = b"Ed"      # Ed25519 over the whole file
KEY_ALG = b"Ed"
UNTRUSTED = "untrusted comment: "
TRUSTED = "trusted comment: "
# DER header of a PKCS#8 Ed25519 private key; the 32-byte seed follows.
PKCS8_PREFIX = bytes.fromhex("302e020100300506032b657004220420")


# --- Ed25519 (RFC 8032, section 6 reference implementation) ---------------------------------

P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493


def _inv(x):
    return pow(x, P - 2, P)


D = -121665 * _inv(121666) % P
_SQRT_M1 = pow(2, (P - 1) // 4, P)


def _sha512_modq(s):
    return int.from_bytes(hashlib.sha512(s).digest(), "little") % Q


def _add(p1, p2):
    a = (p1[1] - p1[0]) * (p2[1] - p2[0]) % P
    b = (p1[1] + p1[0]) * (p2[1] + p2[0]) % P
    c = 2 * p1[3] * p2[3] * D % P
    d = 2 * p1[2] * p2[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f, g * h, f * g, e * h)


def _mul(s, pt):
    out = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        s >>= 1
    return out


def _equal(p1, p2):
    return (p1[0] * p2[2] - p2[0] * p1[2]) % P == 0 and (p1[1] * p2[2] - p2[1] * p1[2]) % P == 0


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * _SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_G_Y = 4 * _inv(5) % P
_G_X = _recover_x(_G_Y, 0)
G = (_G_X, _G_Y, 1, _G_X * _G_Y % P)


def _compress(pt):
    zinv = _inv(pt[2])
    x, y = pt[0] * zinv % P, pt[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _expand(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public(seed):
    return _compress(_mul(_expand(seed)[0], G))


def ed25519_sign(seed, msg):
    a, prefix = _expand(seed)
    pk = _compress(_mul(a, G))
    r = _sha512_modq(prefix + msg)
    rs = _compress(_mul(r, G))
    h = _sha512_modq(rs + pk + msg)
    s = (r + h * a) % Q
    return rs + int.to_bytes(s, 32, "little")


def ed25519_verify(pk, msg, sig):
    if len(pk) != 32 or len(sig) != 64:
        return False
    a = _decompress(pk)
    r = _decompress(sig[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= Q:
        return False
    h = _sha512_modq(sig[:32] + pk + msg)
    return _equal(_mul(s, G), _add(r, _mul(h, a)))


# --- minisign file formats -------------------------------------------------------------------

def load_seed(args):
    """The 32-byte Ed25519 seed from --key (PEM file) or $CATALOG_SIGNING_KEY (PEM text)."""
    if args.key:
        pem = pathlib.Path(args.key).read_text()
    else:
        pem = os.environ.get("CATALOG_SIGNING_KEY")
        if not pem:
            sys.exit("pass --key KEY.pem or set CATALOG_SIGNING_KEY")
    b64 = "".join(l for l in pem.strip().splitlines() if not l.startswith("-----"))
    der = base64.b64decode(b64)
    if len(der) != 48 or not der.startswith(PKCS8_PREFIX):
        sys.exit("not an unencrypted PKCS#8 Ed25519 private key (openssl genpkey -algorithm ed25519)")
    return der[-32:]


def key_id(pk):
    """8-byte key id, derived from the public key so signer and key file always agree."""
    return hashlib.blake2b(pk, digest_size=8).digest()


def public_key_file(pk, comment):
    return f"{UNTRUSTED}{comment}\n" + base64.b64encode(KEY_ALG + key_id(pk) + pk).decode() + "\n"


def parse_public_key(text):
    lines = text.strip().splitlines()
    raw = base64.b64decode(lines[-1])
    if len(raw) != 42 or raw[:2] != KEY_ALG:
        sys.exit("bad public key file")
    return raw[2:10], raw[10:]


def prehash(data):
    return hashlib.blake2b(data, digest_size=64).digest()


def sign(args):
    seed = load_seed(args)
    pk = ed25519_public(seed)
    kid = key_id(pk)
    data = pathlib.Path(args.file).read_bytes()
    sig = ed25519_sign(seed, prehash(data))
    trusted = f"timestamp:{int(time.time())}\tfile:{os.path.basename(args.file)}\thashed"
    global_sig = ed25519_sign(seed, sig + trusted.encode())
    out = args.out or args.file + ".minisig"
    text = (f"{UNTRUSTED}signature from {args.comment}\n"
            + base64.b64encode(SIG_ALG_PREHASHED + kid + sig).decode() + "\n"
            + f"{TRUSTED}{trusted}\n"
            + base64.b64encode(global_sig).decode() + "\n")
    pathlib.Path(out).write_text(text)
    print(f"signed {args.file} -> {out} (key id {kid.hex()})")


def verify(args):
    kid, pk = parse_public_key(pathlib.Path(args.pub).read_text())
    lines = pathlib.Path(args.sig or args.file + ".minisig").read_text().splitlines()
    if len(lines) < 4 or not lines[2].startswith(TRUSTED):
        sys.exit("malformed signature file")
    raw = base64.b64decode(lines[1])
    alg, sig_kid, sig = raw[:2], raw[2:10], raw[10:]
    if alg not in (SIG_ALG_PREHASHED, SIG_ALG_LEGACY) or len(sig) != 64:
        sys.exit("malformed signature")
    if sig_kid != kid:
        sys.exit(f"signature was made with key {sig_kid.hex()}, not {kid.hex()}")
    data = pathlib.Path(args.file).read_bytes()
    message = prehash(data) if alg == SIG_ALG_PREHASHED else data
    if not ed25519_verify(pk, message, sig):
        sys.exit(f"BAD signature for {args.file}")
    trusted = lines[2][len(TRUSTED):]
    if not ed25519_verify(pk, sig + trusted.encode(), base64.b64decode(lines[3])):
        sys.exit("BAD trusted comment signature")
    print(f"Signature and comment signature verified\nTrusted comment: {trusted}")


def pubkey(args):
    print(public_key_file(ed25519_public(load_seed(args)), args.comment), end="")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    p = sub.add_parser("pubkey")
    p.add_argument("--key")
    p.add_argument("--comment", default="pezzotto.ai launcher catalog signing key")
    p.set_defaults(fn=pubkey)
    p = sub.add_parser("sign")
    p.add_argument("--key")
    p.add_argument("--out")
    p.add_argument("--comment", default="pezzotto.ai launcher catalog")
    p.add_argument("file", nargs="?", default="index.json")
    p.set_defaults(fn=sign)
    p = sub.add_parser("verify")
    p.add_argument("--pub", required=True)
    p.add_argument("--sig")
    p.add_argument("file", nargs="?", default="index.json")
    p.set_defaults(fn=verify)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
