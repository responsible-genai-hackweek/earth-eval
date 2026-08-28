#!/usr/bin/env bash
read -rp "Earthdata username: " EDL_USER
read -rsp "Earthdata password: " EDL_PASS
echo

cat > ~/.netrc << NETRC
machine urs.earthdata.nasa.gov
login ${EDL_USER}
password ${EDL_PASS}
NETRC

chmod 600 ~/.netrc
unset EDL_PASS
echo "Wrote ~/.netrc with permissions:"
ls -la ~/.netrc
