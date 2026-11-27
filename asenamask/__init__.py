APP_NAME = "Asena Mask"
APP_VERSION = "1.0.5"          # numeric version (used for the exe / installer)
APP_STAGE = "Beta"
BUILD_NAME = "Genesis"
BUILD_LABEL = "v%s %s  ✦  %s" % (APP_VERSION, APP_STAGE, BUILD_NAME)
__version__ = APP_VERSION
UPDATE_URL = "https://asenatools.com/files/version.json"   # the app checks this file for a newer version
RELEASE_PUBLIC_KEY = "ddb17570b9e30a7bcc545c993ed6df9d29587aa7ef0510fc193145b47028dc78"   # Ed25519 key that signs version.json (tools/sign_release.py); the private half never ships
