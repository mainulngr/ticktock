set dotenv-load := false

venv := ".venv/bin"
python := venv / "python"

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
    @find downloads -type f | sort | sed 's#^downloads/##'

# show per-channel download status
status:
    {{python}} -m ticktock status
