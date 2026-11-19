"""Read-only GitHub PR/issue state probe for the V103 dispatch."""
import json
import sys
import urllib.error
import urllib.request

REPO = "lemoniadowyjohn/carla-control-suite"
BASE = f"https://api.github.com/repos/{REPO}"


def get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def main():
    print("=== PULL REQUESTS ===")
    for n in range(28, 40):
        try:
            d = get(f"{BASE}/pulls/{n}")
        except urllib.error.HTTPError as e:
            print("PR#%-3d HTTP %s" % (n, e.code))
            continue
        except Exception as e:
            print("PR#%-3d ERR %s" % (n, e))
            continue
        print(
            "PR#%-3d %-6s draft=%-5s merged=%-5s mergeable=%-9s head=%s base=%s"
            % (
                n,
                d["state"],
                d.get("draft"),
                d.get("merged"),
                d.get("mergeable_state"),
                d["head"]["sha"][:9],
                d["base"]["ref"][:44],
            )
        )
        print("        title=%s" % d["title"][:88])
        print("        comments=%s review_comments=%s commits=%s files=%s"
              % (d.get("comments"), d.get("review_comments"), d.get("commits"), d.get("changed_files")))

    print("")
    print("=== OPEN ISSUES ===")
    try:
        issues = get(f"{BASE}/issues?state=open&per_page=100")
        for i in issues:
            if "pull_request" in i:
                continue
            print("#%-4d %-9s %s" % (i["number"], i.get("state"), i["title"][:80]))
    except Exception as e:
        print("issues ERR", e)


if __name__ == "__main__":
    main()
