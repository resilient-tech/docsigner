# Homebrew cask for the desktop app.
#
# Lives here as the source of truth; the tap it gets copied into is
# resilient-tech/homebrew-tap, as Casks/docsigner.rb:
#
#     brew install --cask --no-quarantine resilient-tech/tap/docsigner
#
# The --no-quarantine flag is not optional advice, it is the install line.
# Homebrew stamps com.apple.quarantine on every cask it installs and only
# releases it when asked (Library/Homebrew/cask/quarantine.rb), so without the
# flag the app is ad-hoc signed and quarantined, which is exactly the case
# Gatekeeper blocks. With it, the app opens on first double-click and no Apple
# Developer ID is involved. The host ships as a formula instead, which is never
# quarantined at all: host/packaging/homebrew/docsigner-host.rb.
#
# The .dmg this points at is built by desktop/build-macos.sh on a Mac and
# attached to the release by hand. The release workflow builds only the host
# binary today (docs/roadmap.md D6).
cask "docsigner" do
  version "0.2.0"
  # Printed by build-macos.sh at the end of the build.
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"

  # The filename carries no version; the tag in the path is the version.
  url "https://github.com/resilient-tech/docsigner/releases/download/v#{version}/DocSigner.dmg"
  name "DocSigner"
  desc "Batch-sign PDFs locally with a DSC token or a server-held key"
  homepage "https://github.com/resilient-tech/docsigner"

  # Matches LSMinimumSystemVersion in packaging/docsigner-desktop.spec.
  depends_on macos: :big_sur

  app "DocSigner.app"

  # Settings, appearance profiles, uploaded fonts, and any server-held .p12
  # signing keys all live under this one directory. Only `brew uninstall --zap`
  # removes it, which is the point: a plain uninstall leaves the keys alone.
  zap trash: "~/.config/docsigner-desktop"
end
