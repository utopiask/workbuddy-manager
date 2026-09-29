# 根 Makefile：本地与 CI 共用的构建/测试入口。
# 三个子项目各自保留自己的工具链：gateway/（Go）、server/（Python）、web/（Node）。
#
# Python 解释器可由外部覆盖，例如本地依赖装在 .venv 时：
#   make test PYTHON=.venv/bin/python
# CI 使用其自带解释器（默认 python3）。
PYTHON ?= python3

.PHONY: test build gateway web

test:
	cd gateway && go vet ./... && go test ./...
	$(PYTHON) -m unittest discover -s server/tests -t .

# 产物目录 bin/ 由 .gitignore 忽略
gateway:
	cd gateway && go build -o ../bin/wb2api ./cmd/server

web:
	cd web && npm ci && npm run build:export

build: gateway web
