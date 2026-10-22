#!/usr/bin/env python3
"""Keep Git-connected Pages builds from replacing generated package snapshots."""
import json
import os
import urllib.request


def main():
    url = f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/pages/projects/dustymenu-packages"
    headers = {"Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"], "Content-Type": "application/json"}
    def request(method, data=None):
        response = json.load(urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=30))
        if not response.get("success"):
            raise RuntimeError("Pages project configuration request failed")
        return response["result"]
    project = request("GET")
    source = project.get("source")
    if source and source.get("type") == "github":
        source["config"]["production_deployments_enabled"] = False
        source["config"]["preview_deployment_setting"] = "none"
        request("PATCH", json.dumps({"source": source}).encode())
    print("Pages uses generated release snapshots; automatic Git builds disabled")


if __name__ == "__main__": main()
