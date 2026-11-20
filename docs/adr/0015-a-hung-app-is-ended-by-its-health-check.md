# A hung app is ended by its health check

Status: accepted

The app leaves by itself when its event loop hangs: a watchdog thread sees the loop's mark go stale and exits the process (ADR 0007), and Docker starts it again. A hang in C code that holds the GIL stops that thread too, so the process stays: Docker marks the container `unhealthy` and leaves it, with the bot silent until the owner notices (KI-6). Spec 9.1a (section 2.3) gives the job to the one part that runs outside the app's own threads, Docker's health check (`python -m app.healthcheck`, every 30 s). The container runs with Docker's init (`init: true`): the init is PID 1, the app its only child. A **timeout** — the check connected and got no answer in 5 s — is the sign of a hung loop (the kernel still takes the connection); refused, reset or any answer (503 included) is not. The fourth timeout in a row of the same app process (pid and start time from `/proc`, the count in a file of the temp folder) sends SIGKILL to the app; the init exits with it, and `restart: unless-stopped` starts the container again.

Considered and rejected:
- An `autoheal` container that restarts unhealthy containers: it needs the Docker socket (full control of the host) and is a second container to keep, here and on the NAS.
- Docker alone: it does not restart an unhealthy container (only Swarm does), so the hang stays.
- A second watchdog process inside the app: it is a child of the hung process, more code to start and stop with the parts, and it still needs a way to kill its parent from the container.

## Consequences

- ADR 0007 stays: its consequence «the process leaves itself when the loop hangs» is still true for the usual hang. The watchdog acts after 60–90 s and logs the reason; the check acts after about 1.5–2 min, so the watchdog gets the first chance.
- A `/health` that answers 503 never kills: the container is `unhealthy` as before (a part not in order is the runtime's business, not a hang).
- The check runs as root (the image has no `USER` line), the app as `PUID`, so the kill is allowed. A PID 1 cannot be killed from inside its container: without the init (`docker run` without `--init`) the check finds no child of PID 1 and kills nothing, as before.
- The kill line goes to the check's output (`docker inspect`) and to the container's log (the output of PID 1).
- The same works on the NAS: `init: true` and `/proc` are plain Docker on Linux. While the PC sleeps no checks run; after waking the app answers and the count goes back to 0.
