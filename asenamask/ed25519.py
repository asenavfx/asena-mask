"""Pure-Python Ed25519 (RFC 8032 section 6 reference code, public domain). Used to check that update files really come
from Asenavfx. Slow (tens of ms per call) but only runs on a few hundred bytes. Self-test: python -m asenamask.ed25519"""
import hashlib

p = 2 ** 255 - 19
q = 2 ** 252 + 27742317777372353535851937790883648493       # group order (L)


def _inv(x):
    return pow(x, p - 2, p)


d = -121665 * _inv(121666) % p
_SQRT_M1 = pow(2, (p - 1) // 4, p)


def _h(s):
    return int.from_bytes(hashlib.sha512(s).digest(), "little") % q


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % p
    C = 2 * P[3] * Q[3] * d % p
    D = 2 * P[2] * Q[2] % p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F, G * H, F * G, E * H)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _equal(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % p == 0


def _recover_x(y, sign):
    if y >= p:
        return None
    x2 = (y * y - 1) * _inv(d * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = x * _SQRT_M1 % p
    if (x * x - x2) % p != 0:
        return None
    if (x & 1) != sign:
        x = p - x
    return x


_gy = 4 * _inv(5) % p
_gx = _recover_x(_gy, 0)
G = (_gx, _gy, 1, _gx * _gy % p)


def _compress(P):
    zi = _inv(P[2])
    x, y = P[0] * zi % p, P[1] * zi % p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % p)


def _expand(secret):
    if len(secret) != 32:
        raise ValueError("bad secret key length")
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(secret):
    return _compress(_mul(_expand(secret)[0], G))


def sign(secret, msg):
    a, prefix = _expand(secret)
    A = _compress(_mul(a, G))
    r = _h(prefix + msg)
    Rs = _compress(_mul(r, G))
    s = (r + _h(Rs + A + msg) * a) % q
    return Rs + int.to_bytes(s, 32, "little")


def verify(public, msg, signature):
    """True only for a valid signature. Never raises on malformed input."""
    try:
        if len(public) != 32 or len(signature) != 64:
            return False
        A = _decompress(bytes(public))
        R = _decompress(bytes(signature[:32]))
        if A is None or R is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= q:
            return False
        h = _h(bytes(signature[:32]) + bytes(public) + bytes(msg))
        return _equal(_mul(s, G), _add(R, _mul(h, A)))
    except Exception:
        return False


def _selftest():
    # RFC 8032 section 7.1, TEST 1 (empty message)
    sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555"
                        "fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    assert public_key(sk) == pk, "public key mismatch"
    assert sign(sk, b"") == sig, "signature mismatch"
    assert verify(pk, b"", sig), "valid signature rejected"
    assert not verify(pk, b"x", sig), "wrong message accepted"
    assert not verify(pk, b"", sig[:-1] + bytes([sig[-1] ^ 1])), "flipped bit accepted"
    assert not verify(pk, b"", sig[:32]), "short signature accepted"
    print("ed25519 self-test OK (RFC 8032 test 1)")


if __name__ == "__main__":
    _selftest()
