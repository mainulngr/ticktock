set dotenv-load := false

venv := ".venv/bin"
python := venv / "python"
log_max_lines := "10000"

# install dependencies into a local venv
setup:
    python3 -m venv .venv
    {{venv}}/pip install -r requirements.txt

# resolve channel names and stable ids
resolve:
    {{python}} -m ticktock resolve

# run one download cycle
run *args="":
    {{python}} -m ticktock run {{args}}

# run continuously (default 6h)
watch *args="":
    {{python}} -m ticktock watch {{args}}

# stop the running scheduler
stop:
    @if [ -f data/scheduler.pid ]; then PID=$(cat data/scheduler.pid); kill $PID 2>/dev/null || true; kill -- -$PID 2>/dev/null || true; rm -f data/scheduler.pid; fi
    @ps aux | awk '/[t]icktock watch/ {print $2}' | while read pid; do kill "$pid" 2>/dev/null || true; done

# trim scheduler log to the last N lines
log-trim:
    @if [ -f data/scheduler.log ]; then tail -n {{log_max_lines}} data/scheduler.log > data/scheduler.log.tmp && mv data/scheduler.log.tmp data/scheduler.log; fi

# clear the scheduler log
log-clear:
    @if [ -f data/scheduler.log ]; then > data/scheduler.log; fi

# restart the scheduler (stops any existing one first, trims log)
restart *args="--max-downloads 20 --interval 600":
    @just stop
    @just log-trim
    @nohup {{python}} -m ticktock watch {{args}} >> data/scheduler.log 2>&1 & echo $! > data/scheduler.pid

# test one download per channel
verify:
    {{python}} -m ticktock run --force --max-downloads 1

# clean runtime data (downloads + state)
clean:
    rm -rf downloads data

# full clean slate: delete all downloads and state, with confirmation
[confirm("This will delete all downloaded videos and state. Continue? [y/N]")]
clean-slate: clean

# show summary of downloaded files
summary:
    @DIR=$({{python}} -c "from ticktock.config import load_env_config; print(load_env_config().download_base_dir)") && find "$DIR" -type f | sort | sed "s#^$DIR/##"

# show per-channel download status
status:
    {{python}} -m ticktock status

# export browser cookies to cookies.txt (run while logged into the browser)
refresh-cookies:
    {{python}} -m ticktock refresh-cookies
