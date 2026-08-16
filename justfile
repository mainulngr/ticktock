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
    {{python}} -m ticktock {{args}} run

# run continuously (default 6h)
watch *args="":
    {{python}} -m ticktock {{args}} watch

# test one download per channel
verify:
    {{python}} -m ticktock --force run --max-downloads 1

# clean runtime data (downloads + state)
clean:
    rm -rf downloads data

# show summary of downloaded files
summary:
    @find downloads -type f | sort | sed 's#^downloads/##'
