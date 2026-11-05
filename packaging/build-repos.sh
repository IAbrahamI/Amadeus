#!/usr/bin/env bash
# Turns the packages in dist/ into signed apt, dnf and pacman repositories in site/, for GitHub Pages. Needs the signing
# key imported in gpg, its passphrase in REPO_GPG_PASSPHRASE, and dpkg-dev, apt-utils, createrepo-c and Docker.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf site; mkdir -p site/apt/pool site/apt/dists/stable/main/binary-amd64 site/rpm site/arch/x86_64
sign() { gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 "$@" 3<<<"$REPO_GPG_PASSPHRASE"; }
cp packaging/amadeus-repo.gpg site/

# apt
cp dist/*.deb site/apt/pool/
(cd site/apt && dpkg-scanpackages --arch amd64 pool > dists/stable/main/binary-amd64/Packages && gzip -k9 dists/stable/main/binary-amd64/Packages)
(cd site/apt/dists/stable && apt-ftparchive -o APT::FTPArchive::Release::Origin=Amadeus -o APT::FTPArchive::Release::Label=Amadeus \
  -o APT::FTPArchive::Release::Suite=stable -o APT::FTPArchive::Release::Codename=stable -o APT::FTPArchive::Release::Architectures=amd64 \
  -o APT::FTPArchive::Release::Components=main release . > Release)
sign --armor --detach-sign --output site/apt/dists/stable/Release.gpg site/apt/dists/stable/Release
sign --armor --clearsign --output site/apt/dists/stable/InRelease site/apt/dists/stable/Release

# dnf
cp dist/*.rpm site/rpm/
createrepo_c --quiet site/rpm
sign --armor --detach-sign --output site/rpm/repodata/repomd.xml.asc site/rpm/repodata/repomd.xml

# pacman (repo-add only comes with Arch)
cp dist/*.pkg.tar.zst site/arch/x86_64/
docker run --rm -v "$PWD/site/arch/x86_64:/repo" archlinux:latest bash -c 'cd /repo && repo-add --quiet amadeus.db.tar.gz ./*.pkg.tar.zst && chmod -R a+rwX .'
(cd site/arch/x86_64 && rm -f amadeus.db amadeus.files && cp amadeus.db.tar.gz amadeus.db && cp amadeus.files.tar.gz amadeus.files)
for f in site/arch/x86_64/*.pkg.tar.zst site/arch/x86_64/amadeus.db; do sign --detach-sign --output "$f.sig" "$f"; done

cat > site/index.html <<'H'
<!doctype html><meta charset="utf-8"><title>Amadeus packages</title>
<p>Package repositories for <a href="https://github.com/IAbrahamI/Amadeus">Amadeus</a>. See its docs/INSTALL.md for how to add them.</p>
H
find site -type f | sort
