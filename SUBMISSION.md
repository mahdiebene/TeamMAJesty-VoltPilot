# Submission desk — Team MAJesty / VoltPilot

## Form links

| Form field | Value / action |
| --- | --- |
| GitHub / source code | https://github.com/mahdiebene/TeamMAJesty-VoltPilot |
| Project GitHub README | https://github.com/mahdiebene/TeamMAJesty-VoltPilot/blob/main/README.md |
| Live project demo / API base | http://35.222.65.204 |
| 3-minute public video | Record and upload using `VIDEO_SCRIPT.md`; no video is uploaded by this repository. |

**Live backend verified:** `/health` returns 200 and SAMPLE-01 passed real model
interpretation, independent replay and optimal cost in 1.784 seconds.
All ten public cases then passed live: 0 failures, p50 6.341s, p95 8.045s.
The Vercel frontend is prepared with same-origin API rewrites; its final URL still
needs deployment verification. Keep the VM running and its external IP allocated
through judging. HTTP is allowed by the rubric but is unencrypted: use only synthetic
challenge data. A temporary HTTPS mirror is available at
https://fame-choice-amended-diabetes.trycloudflare.com; this Cloudflare **quick
tunnel** has no uptime guarantee and changes if its process restarts.
Recheck the fixed-address URL from outside the VM before submitting.

## Mandatory release gates

- [x] Configure the model credential in backend runtime, not frontend/source.
- [x] Recreate the managed container; `/health` returns 200 `{"status":"ok"}`.
- [x] One live SAMPLE-01 request passes ground-truth interpretation, replay,
      optimal cost (38,365 BDT), and the 30-second limit.
- [x] All ten public cases pass through the real model with ground-truth validation.
- [x] All seven independently labeled paraphrases pass live.
- [ ] Both endpoints are externally reachable, without login, for the judging window.
- [ ] Publish a matching immutable Docker image and verify pull/run by digest.
- [ ] Give organizers image access and securely arrange runtime model credentials.
- [ ] Keep the repository private during the event; make it public **after the
      submission deadline**, as the official guide requires. Verify reveal-time
      repository creation compliance; it is not certified by these tests.
- [ ] Record/upload a video no longer than 3 minutes and verify public playback.
- [ ] Enter team details, all required links, and actually submit the form.

## Score-aware priorities from the official PDFs

| Category | Points |
| --- | ---: |
| LLM directive interpretation | 25 |
| Directive application and constraint correctness | 25 |
| Optimization quality | 10 |
| API contract and schema | 10 |
| Performance and reliability | 10 |
| Deployment and Docker fallback | 10 |
| Documentation and local reproducibility | 10 |

The video is mandatory and the **first tie-break**, but carries no base points.
An LLM must actually interpret the notes; using AI only for summaries is not eligible.
Public samples are not hidden tests, and no shortlist/rank is guaranteed.

## Owner-only secret setup on the VM

Run in interactive GCP SSH, never paste the key into chat or the submission form:

```bash
sudo python3 -B /opt/voltpilot/current/scripts/configure_model.py
sudo bash /opt/voltpilot/current/deploy/start.sh \
  "$(sudo cat /opt/voltpilot/current-image-id)" --replace --public-http
```

Use the helper's `--rotate` option only when a configuration already exists.
Revoke any previously exposed credential at the provider. A Docker restart alone
does not reload the runtime env-file. See `deploy/README.md` for bounded live tests.