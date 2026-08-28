#!/usr/bin/env bash
read -rsp "Paste your Earthdata token: " EARTHDATA_TOKEN
echo
export EARTHDATA_TOKEN
python3 -c "
import earthaccess
auth = earthaccess.login(strategy='environment', persist=False)
print('Authenticated:', auth.authenticated)
"
