#!/usr/bin/env python3
"""
twohundredseventyone local runner.

This is a practical interpreter for the plain-English 271 syntax. It is not a
complete production compiler yet, but it is intentionally real: programs are
parsed, executed, tested, and reported with plain-English errors.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import queue
import re
import shutil
import sys
import threading
import time
import zipfile
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib import error as url_error
from urllib import request as url_request
from typing import Any, Callable


VERSION = "0.27.0"


class PlainError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.frames: list[tuple[str, int, str]] = []

    def add_frame(self, source: str, line: int, text: str) -> None:
        frame = (source, line, clean_name(text))
        if self.frames and self.frames[-1] == frame:
            return
        self.frames.append(frame)

    def __str__(self) -> str:
        return self.message


class StopRepeat(Exception):
    pass


class SkipRepeat(Exception):
    pass


class NeedStopped(Exception):
    def __init__(self, value: Any):
        self.value = value


class TaskHandle:
    def __init__(self, name: str, target: Callable[[], Any]):
        self.name = name
        self.result: Any = None
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self.run, args=(target,), daemon=True)
        self.thread.start()

    def run(self, target: Callable[[], Any]) -> None:
        try:
            self.result = target()
        except BaseException as error:
            self.error = error

    def await_result(self) -> Any:
        self.thread.join()
        if self.error:
            raise self.error
        return self.result

    def is_done(self) -> bool:
        return not self.thread.is_alive()


class Channel:
    def __init__(self, capacity: int = 0, item_type: str | None = None, runner: Any = None):
        self.queue: queue.Queue[Any] = queue.Queue(maxsize=max(0, int(capacity)))
        self.item_type = item_type
        self.runner = runner
        self.closed = False

    def send(self, value: Any) -> Any:
        if self.closed:
            raise PlainError("Cannot send to a closed channel.")
        if self.item_type and self.runner:
            self.runner.ensure_type(value, self.item_type, "Channel message")
        self.queue.put(value)
        return value

    def receive(self) -> Any:
        value = self.queue.get()
        return value

    def close(self) -> None:
        self.closed = True
        self.queue.put(None)


class TeachingReturned(Exception):
    def __init__(self, value: Any):
        self.value = value


@dataclass
class Result:
    ok: bool
    value: Any

    @staticmethod
    def success(value: Any) -> "Result":
        return Result(True, value)

    @staticmethod
    def failure(value: Any) -> "Result":
        return Result(False, value)


class TypedList(list):
    def __init__(self, values: list[Any] | None = None, item_type: str | None = None, runner: Any = None):
        super().__init__(values or [])
        self.item_type = item_type
        self.runner = runner


class TypedSet(set):
    def __init__(self, values: Any = None, item_type: str | None = None, runner: Any = None):
        super().__init__(values or [])
        self.item_type = item_type
        self.runner = runner


class MapValue:
    def __init__(self, entries: list[tuple[Any, Any]] | None = None, key_type: str | None = None, value_type: str | None = None, runner: Any = None):
        self.entries: list[tuple[Any, Any]] = []
        self.key_type = key_type
        self.value_type = value_type
        self.runner = runner
        for key, value in entries or []:
            self[key] = value

    def find_index(self, key: Any) -> int | None:
        for index, (stored_key, _value) in enumerate(self.entries):
            if stored_key == key:
                return index
        return None

    def __setitem__(self, key: Any, value: Any) -> None:
        if self.runner and self.key_type:
            self.runner.ensure_type(key, self.key_type, "Map key")
        if self.runner and self.value_type:
            self.runner.ensure_type(value, self.value_type, "Map value")
        index = self.find_index(key)
        if index is None:
            self.entries.append((key, value))
        else:
            self.entries[index] = (self.entries[index][0], value)

    def __getitem__(self, key: Any) -> Any:
        index = self.find_index(key)
        if index is None:
            raise KeyError(key)
        return self.entries[index][1]

    def __contains__(self, key: Any) -> bool:
        return self.find_index(key) is not None

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.keys())

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, dict):
            other = MapValue(list(other.items()))
        if not isinstance(other, MapValue) or len(self) != len(other):
            return False
        return all(key in other and other[key] == value for key, value in self.entries)

    def keys(self) -> list[Any]:
        return [key for key, _value in self.entries]

    def values(self) -> list[Any]:
        return [value for _key, value in self.entries]

    def items(self) -> list[tuple[Any, Any]]:
        return list(self.entries)

    def get(self, key: Any, default: Any = None) -> Any:
        return self[key] if key in self else default

    def pop(self, key: Any, default: Any = None) -> Any:
        index = self.find_index(key)
        if index is None:
            return default
        _key, value = self.entries.pop(index)
        return value

    def copy(self) -> "MapValue":
        return MapValue(self.entries, key_type=self.key_type, value_type=self.value_type, runner=self.runner)

    def update(self, other: Any) -> None:
        if isinstance(other, MapValue):
            items = other.items()
        elif isinstance(other, dict):
            items = list(other.items())
        else:
            raise PlainError("Map Merge needs maps.")
        for key, value in items:
            self[key] = value


@dataclass
class Line:
    text: str
    number: int
    indent: int
    children: list["Line"] = field(default_factory=list)
    source: str = "program"


@dataclass
class Parameter:
    name: str
    type_name: str | None = None
    default: str | None = None
    variadic: bool = False


@dataclass
class TypeDef:
    name: str
    fields: list[str] = field(default_factory=list)
    field_types: dict[str, str] = field(default_factory=dict)
    private_fields: set[str] = field(default_factory=set)
    methods: dict[str, "Teaching"] = field(default_factory=dict)
    private_methods: set[str] = field(default_factory=set)
    parent: str | None = None
    contracts: list[str] = field(default_factory=list)


@dataclass
class Instance:
    type_name: str
    fields: dict[str, Any]


@dataclass
class ModuleValue:
    name: str
    values: dict[str, Any]


@dataclass
class Teaching:
    name: str
    parameters: list[Parameter]
    body: list[Line]
    closure: "Environment"
    runner: "Runner"
    source: str = "program"
    line_number: int = 0
    owner_type: str | None = None

    def call(self, positional: list[Any], named: dict[str, Any], self_value: Any = None) -> Any:
        local = Environment(parent=self.closure, runner=self.runner, in_teaching=True)
        pos = list(positional)
        if self_value is not None:
            pos.insert(0, self_value)

        index = 0
        for parameter in self.parameters:
            key = normalize(parameter.name)
            if parameter.variadic:
                values = pos[index:]
                if parameter.type_name:
                    for value in values:
                        self.runner.ensure_type(value, parameter.type_name, parameter.name)
                list_type = f"List of {parameter.type_name}" if parameter.type_name else None
                local.define(parameter.name, values, type_name=list_type)
                index = len(pos)
                continue
            if key in named:
                value = named[key]
            elif index < len(pos):
                value = pos[index]
                index += 1
            elif parameter.default is not None:
                value = self.runner.eval_expression(parameter.default, local)
            else:
                raise PlainError(f"{self.name} needs a value for {parameter.name}.")
            if parameter.type_name:
                self.runner.ensure_type(value, parameter.type_name, parameter.name)
            local.define(parameter.name, value, type_name=parameter.type_name)

        try:
            return self.runner.execute_block(self.body, local)
        except TeachingReturned as returned:
            return returned.value
        except PlainError as error:
            error.add_frame(self.source, self.line_number, f"while using {self.name}")
            raise


class Environment:
    def __init__(self, parent: "Environment | None" = None, runner: "Runner | None" = None, in_teaching: bool = False):
        self.parent = parent
        self.runner = runner if runner is not None else (parent.runner if parent else None)
        self.values: dict[str, Any] = {}
        self.value_types: dict[str, str] = {}
        self.constants: set[str] = set()
        self.in_teaching = in_teaching

    def define(self, name: str, value: Any, constant: bool = False, type_name: str | None = None) -> None:
        key = normalize(name)
        if type_name and self.runner:
            value = self.runner.apply_runtime_type(value, type_name)
        self.values[key] = value
        if type_name:
            self.value_types[key] = type_name
        elif self.runner:
            inferred = self.runner.runtime_type_name(value)
            if inferred:
                self.value_types[key] = inferred
        if constant:
            self.constants.add(key)

    def assign(self, name: str, value: Any) -> None:
        key = normalize(name)
        env = self.find_env(key)
        if env is None:
            raise PlainError(f"{clean_name(name)} has not been made yet.")
        if key in env.constants:
            raise PlainError(f"{clean_name(name)} is kept and cannot be changed.")
        expected_type = env.value_types.get(key)
        if expected_type and env.runner:
            env.runner.ensure_type(value, expected_type, name)
            value = env.runner.apply_runtime_type(value, expected_type)
        env.values[key] = value

    def get(self, name: str) -> Any:
        key = normalize(name)
        env = self.find_env(key)
        if env is None:
            raise PlainError(f"I do not know the name {clean_name(name)}.")
        return env.values[key]

    def find_env(self, key: str) -> "Environment | None":
        if key in self.values:
            return self
        if self.parent:
            return self.parent.find_env(key)
        return None


def normalize(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        name = name[1:-1]
    name = re.sub(r"[^A-Za-z0-9]+", " ", name)
    return " ".join(name.lower().split())


def clean_name(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        return name[1:-1]
    return " ".join(name.split())


def split_outside_quotes(text: str, separator: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            i += 1
            continue
        if not in_string and text.startswith(separator, i):
            pieces.append(text[start:i].strip())
            i += len(separator)
            start = i
            continue
        i += 1
    pieces.append(text[start:].strip())
    return [piece for piece in pieces if piece]


def split_once_outside_quotes(text: str, separator: str, last: bool = False) -> tuple[str, str] | None:
    matches: list[int] = []
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            i += 1
            continue
        if not in_string and text.startswith(separator, i):
            matches.append(i)
            i += len(separator)
            continue
        i += 1
    if not matches:
        return None
    index = matches[-1] if last else matches[0]
    return text[:index].strip(), text[index + len(separator):].strip()


def starts(text: str, prefix: str) -> bool:
    return text.lower().startswith(prefix.lower())


def strip_prefix(text: str, prefix: str) -> str:
    if not starts(text, prefix):
        raise PlainError(f"Expected {prefix}.")
    return text[len(prefix):].strip()


def parse_program(source: str, source_label: str = "program") -> list[Line]:
    raw_lines = source.splitlines()
    kept: list[tuple[int, str, int]] = []
    skipping_notes_at: int | None = None

    for number, raw in enumerate(raw_lines, start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip("\t "))]:
            raise PlainError(f"Line {number} uses a tab. Use spaces for indentation.")
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        text = raw[indent:].rstrip()
        if number == 1:
            text = text.lstrip("\ufeff")
        if skipping_notes_at is not None:
            if indent > skipping_notes_at:
                continue
            skipping_notes_at = None
        if starts(text, "Note "):
            continue
        if text == "Notes":
            skipping_notes_at = indent
            continue
        kept.append((indent, text, number))

    root = Line("<root>", 0, -2, source=source_label)
    stack: list[Line] = [root]
    for indent, text, number in kept:
        while stack and indent <= stack[-1].indent:
            stack.pop()
        parent = stack[-1]
        expected = parent.indent + 2
        if parent is root:
            expected = 0
        if indent != expected:
            raise PlainError(f"Line {number} is indented with {indent} spaces. Use {expected} spaces here.")
        node = Line(text=text, number=number, indent=indent, source=source_label)
        parent.children.append(node)
        stack.append(node)
    return root.children


class Runner:
    def __init__(self, argv: list[str] | None = None, base_dir: Path | None = None):
        self.argv = argv or []
        self.base_dir = base_dir or Path.cwd()
        self.output: list[str] = []
        self.types: dict[str, TypeDef] = {}
        self.contracts: dict[str, list[str]] = {}
        self.aliases: dict[str, str] = {}
        self.builtins: dict[str, Callable[[list[Any], dict[str, Any]], Any]] = {}
        self.spoken_aliases: dict[str, Any] = {normalize("jew"): 271}
        self.loaded_modules: set[Path] = set()
        self.private_access_stack: list[str] = []
        self.global_env = Environment(runner=self)
        self.install_builtins()

    def say(self, value: Any) -> None:
        if isinstance(value, str) and normalize(value) in self.spoken_aliases:
            value = self.spoken_aliases[normalize(value)]
        text = self.to_text(value)
        self.output.append(text)
        print(text)

    def install_builtins(self) -> None:
        def add(name: str, fn: Callable[[list[Any], dict[str, Any]], Any]) -> None:
            self.builtins[normalize(name)] = fn

        self.global_env.define("jew", 271, constant=True, type_name="Int")

        add("String Trim", lambda args, named: str(args[0]).strip())
        add("String Lower", lambda args, named: str(args[0]).lower())
        add("String Upper", lambda args, named: str(args[0]).upper())
        add("String Contains", lambda args, named: str(args[1]) in str(args[0]))
        add("String Split", lambda args, named: str(args[0]).split(str(named.get("by", args[1] if len(args) > 1 else " "))))
        add("String Join", lambda args, named: str(named.get("by", args[1] if len(args) > 1 else "")).join(map(str, args[0])))
        add("String Starts With", lambda args, named: str(args[0]).startswith(str(args[1])))
        add("String Ends With", lambda args, named: str(args[0]).endswith(str(args[1])))

        add("List Add", self.builtin_list_add)
        add("List Replace At", self.builtin_list_replace_at)
        add("List Map", self.builtin_list_map)
        add("List Filter", self.builtin_list_filter)
        add("List Reduce", self.builtin_list_reduce)
        add("List Sort", self.builtin_list_sort)
        add("List Zip", lambda args, named: list(zip(args[0], args[1])))
        add("Map Has", self.builtin_map_has)
        add("Map Get", self.builtin_map_get)
        add("Map Put", self.builtin_map_put)
        add("Map Remove", self.builtin_map_remove)
        add("Map Merge", self.builtin_map_merge)
        add("Map Keys", self.builtin_map_keys)
        add("Map Values", self.builtin_map_values)
        add("Map Entries", self.builtin_map_entries)
        add("Set Add", self.builtin_set_add)
        add("Set From", lambda args, named: TypedSet(args[0]))

        add("Math Sqrt", lambda args, named: math.sqrt(args[0]))
        add("Math Clamp", lambda args, named: max(args[1], min(args[0], args[2])))
        add("Math Round", lambda args, named: round(args[0]))

        add("Int Parse", self.builtin_int_parse)
        add("Float Parse", self.builtin_float_parse)

        add("File Exists", lambda args, named: self.resolve_path(args[0]).exists())
        add("File Read", self.builtin_file_read)
        add("File Write", self.builtin_file_write)
        add("File Delete", self.builtin_file_delete)
        add("File Walk", self.builtin_file_walk)

        add("Json Parse", self.builtin_json_parse)
        add("Json Serialize", lambda args, named: Result.success(json.dumps(self.to_jsonable(args[0]), indent=2)))

        add("Time Now", lambda args, named: time.localtime())
        add("Time Format", self.builtin_time_format)
        add("Time Sleep", lambda args, named: time.sleep(float(named.get("seconds", args[0] if args else 0))) or None)

        add("OS Args", lambda args, named: self.argv)
        add("OS Env", lambda args, named: os.environ.get(str(args[0])))
        add("OS Exit", lambda args, named: sys.exit(int(args[0])))

        add("Regex Match", self.builtin_regex_match)
        add("Regex Replace", self.builtin_regex_replace)

        add("Http Response", lambda args, named: {"status": named.get("status", 200), "text": named.get("text"), "json": named.get("json")})
        add("Http Get", self.builtin_http_get)
        add("Http Post", self.builtin_http_post)
        add("Http Serve", self.builtin_http_serve)

        add("Async All", self.builtin_async_all)
        add("Async Race", self.builtin_async_race)

    def resolve_path(self, value: Any) -> Path:
        path = Path(str(value))
        if path.is_absolute():
            return path
        return self.base_dir / path

    def runtime_type_name(self, value: Any) -> str | None:
        if value is None:
            return "Nothing"
        if isinstance(value, bool):
            return "Bool"
        if isinstance(value, int):
            return "Int"
        if isinstance(value, float):
            return "Float"
        if isinstance(value, str):
            return "String"
        if isinstance(value, TypedList) and value.item_type:
            return f"List of {value.item_type}"
        if isinstance(value, TypedSet) and value.item_type:
            return f"Set of {value.item_type}"
        if isinstance(value, list):
            item_type = self.common_runtime_type([self.runtime_type_name(item) for item in value])
            return f"List of {item_type}" if item_type else "List"
        if isinstance(value, set):
            item_type = self.common_runtime_type([self.runtime_type_name(item) for item in value])
            return f"Set of {item_type}" if item_type else "Set"
        if isinstance(value, tuple):
            item_types = [self.runtime_type_name(item) or "Anything" for item in value]
            return f"Tuple of {' and '.join(item_types)}" if item_types else "Tuple"
        if isinstance(value, MapValue) and value.key_type and value.value_type:
            return f"Map of {value.key_type} to {value.value_type}"
        if self.is_map_value(value):
            items = self.map_items(value)
            key_type = self.common_runtime_type([self.runtime_type_name(key) for key, _item in items])
            value_type = self.common_runtime_type([self.runtime_type_name(item) for _key, item in items])
            return f"Map of {key_type} to {value_type}" if key_type and value_type else "Map"
        if isinstance(value, Result):
            inner = self.runtime_type_name(value.value)
            return f"Result of {inner}" if inner else "Result"
        if isinstance(value, TaskHandle):
            return "Task"
        if isinstance(value, Channel):
            return f"Channel of {value.item_type}" if value.item_type else "Channel"
        if isinstance(value, Instance):
            return value.type_name
        return None

    def common_runtime_type(self, types: list[str | None]) -> str | None:
        clean = [type_name for type_name in types if type_name]
        if not clean:
            return None
        absence = any(type_name == "Nothing" or starts(type_name, "Maybe ") for type_name in clean)
        if absence:
            present = [
                strip_prefix(type_name, "Maybe ") if starts(type_name, "Maybe ") else type_name
                for type_name in clean
                if type_name != "Nothing"
            ]
            if not present:
                return "Nothing"
            return self.make_runtime_maybe_type(self.common_runtime_type(present) or "Anything")
        first = clean[0]
        if all(type_name == first for type_name in clean):
            return first
        if all(type_name in {"Int", "Float"} for type_name in clean):
            return "Float"
        return "Anything"

    def make_runtime_maybe_type(self, type_name: str) -> str:
        if type_name == "Nothing":
            return "Maybe Anything"
        if starts(type_name, "Maybe "):
            return type_name
        return f"Maybe {type_name}"

    def apply_runtime_type(self, value: Any, type_name: str) -> Any:
        resolved = self.resolve_type_name(type_name)
        if starts(resolved, "Maybe "):
            return None if value is None else self.apply_runtime_type(value, strip_prefix(resolved, "Maybe "))
        if starts(resolved, "List of ") and isinstance(value, list):
            item_type = strip_prefix(resolved, "List of ")
            typed = value if isinstance(value, TypedList) else TypedList(list(value), runner=self)
            typed.item_type = item_type
            typed.runner = self
            for item in typed:
                self.ensure_type(item, item_type, "List item")
            return typed
        if starts(resolved, "Set of ") and isinstance(value, set):
            item_type = strip_prefix(resolved, "Set of ")
            typed = value if isinstance(value, TypedSet) else TypedSet(value, runner=self)
            typed.item_type = item_type
            typed.runner = self
            for item in typed:
                self.ensure_type(item, item_type, "Set item")
            return typed
        if starts(resolved, "Map of ") and self.is_map_value(value):
            split = split_once_outside_quotes(strip_prefix(resolved, "Map of "), " to ")
            if split:
                if not isinstance(value, MapValue):
                    value = MapValue(list(value.items()), runner=self)
                value.key_type = split[0]
                value.value_type = split[1]
                value.runner = self
                for key, item in value.items():
                    self.ensure_type(key, split[0], "Map key")
                    self.ensure_type(item, split[1], "Map value")
            return value
        return value

    def to_language_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return MapValue([(self.to_language_value(key), self.to_language_value(item)) for key, item in value.items()])
        if isinstance(value, list):
            return [self.to_language_value(item) for item in value]
        return value

    def is_map_value(self, value: Any) -> bool:
        return isinstance(value, (MapValue, dict))

    def map_items(self, value: Any) -> list[tuple[Any, Any]]:
        if isinstance(value, MapValue):
            return value.items()
        if isinstance(value, dict):
            return list(value.items())
        raise PlainError("This value is not a map.")

    def map_keys(self, value: Any) -> list[Any]:
        return [key for key, _item in self.map_items(value)]

    def map_get_value(self, value: Any, key: Any, default: Any = None) -> Any:
        if isinstance(value, MapValue):
            return value.get(key, default)
        if isinstance(value, dict):
            try:
                return value.get(key, default)
            except TypeError:
                raise PlainError("This Python-backed map cannot use that key. Use a 271 map value.")
        raise PlainError("Map Get needs a map.")

    def map_set_value(self, value: Any, key: Any, item: Any) -> None:
        if isinstance(value, MapValue):
            value[key] = item
            return
        if isinstance(value, dict):
            try:
                value[key] = item
                return
            except TypeError:
                raise PlainError("This Python-backed map cannot use that key. Use a 271 map value.")
        raise PlainError("Map Put needs a map.")

    def execute(self, source: str, run_main: bool = True, source_label: str = "program") -> Any:
        program = parse_program(source, source_label=source_label)
        return self.execute_program(program, run_main=run_main)

    def execute_program(self, program: list[Line], run_main: bool = True) -> Any:
        result = self.execute_block(program, self.global_env)
        if run_main and normalize("Main") in self.global_env.values:
            main = self.global_env.get("Main")
            if isinstance(main, Teaching):
                return main.call([], {})
        return result

    def execute_block(self, lines: list[Line], env: Environment) -> Any:
        index = 0
        last_value: Any = None
        while index < len(lines):
            line = lines[index]
            text = line.text
            try:
                if starts(text, "Otherwise") or starts(text, "Catch ") or text == "Finally":
                    index += 1
                    continue
                if starts(text, "If "):
                    last_value, index = self.execute_if_chain(lines, index, env)
                    continue
                if starts(text, "Match "):
                    last_value = self.execute_match(line, env)
                    index += 1
                    continue
                if starts(text, "Repeat "):
                    last_value = self.execute_repeat(line, env)
                    index += 1
                    continue
                if text == "Try":
                    last_value, index = self.execute_try(lines, index, env)
                    continue
                if (starts(text, "Make ") or starts(text, "Keep ")) and self.make_expression_starts(text, "If "):
                    last_value, index = self.execute_make_if_chain(lines, index, env, constant=starts(text, "Keep "))
                    continue
                last_value = self.execute_line(line, env)
                index += 1
            except PlainError as error:
                error.add_frame(line.source, line.number, line.text)
                raise
        return last_value

    def make_expression_starts(self, text: str, prefix: str) -> bool:
        keyword = "Make " if starts(text, "Make ") else "Keep " if starts(text, "Keep ") else ""
        if not keyword:
            return False
        split = split_once_outside_quotes(strip_prefix(text, keyword), " be ")
        return bool(split and starts(split[1], prefix))

    def execute_line(self, line: Line, env: Environment) -> Any:
        text = line.text
        if starts(text, "Bring "):
            return self.execute_bring(strip_prefix(text, "Bring "), env)
        if starts(text, "Type "):
            self.execute_type(strip_prefix(text, "Type "))
            return None
        if starts(text, "Contract "):
            self.define_contract(line)
            return None
        if starts(text, "Record ") or starts(text, "Object ") or starts(text, "Problem "):
            self.define_type(line, env)
            return None
        if starts(text, "Async Teach "):
            self.define_teaching(line, env, async_prefix=True)
            return None
        if starts(text, "Test Teach "):
            self.define_teaching(line, env, test_prefix=True)
            return None
        if starts(text, "Teach using "):
            return self.eval_expression(text, env)
        if starts(text, "Teach "):
            self.define_teaching(line, env)
            return None
        if starts(text, "Make "):
            return self.execute_make(line, env, constant=False)
        if starts(text, "Keep "):
            return self.execute_make(line, env, constant=True)
        if starts(text, "Change "):
            return self.execute_change(line, env)
        if starts(text, "Say "):
            value = self.eval_expression(strip_prefix(text, "Say "), env)
            self.say(value)
            return value
        if starts(text, "Expect "):
            return self.execute_expect(line, env)
        if starts(text, "Ignore Result "):
            value = self.eval_expression(strip_prefix(text, "Ignore Result "), env)
            if not isinstance(value, Result):
                raise PlainError("Ignore Result needs a Result value.")
            return None
        if starts(text, "Need "):
            return self.need(self.eval_expression(strip_prefix(text, "Need "), env))
        if starts(text, "Success "):
            value = Result.success(self.eval_expression(strip_prefix(text, "Success "), env))
            if env.in_teaching:
                raise TeachingReturned(value)
            return value
        if starts(text, "Failure "):
            value = Result.failure(self.eval_expression(strip_prefix(text, "Failure "), env))
            if env.in_teaching:
                raise TeachingReturned(value)
            return value
        if starts(text, "Send "):
            return self.execute_send(text, env)
        if text == "Stop":
            raise StopRepeat()
        if text == "Skip":
            raise SkipRepeat()
        if starts(text, "Await "):
            return self.eval_expression(strip_prefix(text, "Await "), env)
        if text:
            if text == "Map with":
                return self.eval_map_lines(line.children, env)
            value = self.eval_expression(text, env)
            if isinstance(value, Result):
                raise PlainError("This Result is ignored. Use Need, Match, Make, or Ignore Result.")
            return value
        return None

    def execute_make(self, line: Line, env: Environment, constant: bool) -> Any:
        keyword = "Keep " if constant else "Make "
        rest = strip_prefix(line.text, keyword)
        split = split_once_outside_quotes(rest, " be ")
        if not split:
            raise PlainError(f"Line {line.number} needs the word be.")
        names_text, expression = split
        annotation = None
        annotated = split_once_outside_quotes(expression, " as ", last=True)
        if annotated:
            expression, annotation = annotated
        if expression == "Text":
            value = "\n".join(child.text for child in line.children)
        elif expression == "Map with":
            value = self.eval_map_lines(line.children, env)
        elif starts(expression, "If "):
            value, _index = self.execute_if_chain([Line(expression, line.number, line.indent, line.children, source=line.source)], 0, env)
        elif starts(expression, "Match "):
            value = self.execute_match(Line(expression, line.number, line.indent, line.children, source=line.source), env)
        else:
            value = self.eval_expression(expression, env)
        self.ensure_absence_is_explicit(value, annotation, names_text)
        if annotation:
            self.ensure_type(value, annotation, names_text)
        names = [name.strip() for name in split_outside_quotes(names_text, " and ")]
        self.bind_names(names, value, env, constant=constant, type_name=annotation)
        return value

    def execute_make_if_chain(self, lines: list[Line], start_index: int, env: Environment, constant: bool) -> tuple[Any, int]:
        line = lines[start_index]
        keyword = "Keep " if constant else "Make "
        split = split_once_outside_quotes(strip_prefix(line.text, keyword), " be ")
        if not split:
            raise PlainError(f"Line {line.number} needs the word be.")
        names_text, expression = split
        annotation = None
        annotated = split_once_outside_quotes(expression, " as ", last=True)
        if annotated:
            expression, annotation = annotated
        candidates: list[tuple[str | None, list[Line]]] = [(strip_prefix(expression, "If "), line.children)]
        index = start_index + 1
        while index < len(lines):
            text = lines[index].text
            if starts(text, "Otherwise if "):
                candidates.append((strip_prefix(text, "Otherwise if "), lines[index].children))
                index += 1
            elif text == "Otherwise":
                candidates.append((None, lines[index].children))
                index += 1
                break
            else:
                break
        value = None
        for condition, children in candidates:
            if condition is None or self.truthy(self.eval_expression(condition, env)):
                value = self.execute_block(children, env)
                break
        if annotation:
            self.ensure_type(value, annotation, names_text)
        self.ensure_absence_is_explicit(value, annotation, names_text)
        names = [name.strip() for name in split_outside_quotes(names_text, " and ")]
        self.bind_names(names, value, env, constant=constant, type_name=annotation)
        return value, index

    def execute_change(self, line: Line, env: Environment) -> Any:
        rest = strip_prefix(line.text, "Change ")
        split = split_once_outside_quotes(rest, " to ")
        if not split:
            raise PlainError(f"Line {line.number} needs the word to.")
        place, expression = split
        value = self.eval_expression(expression, env)
        field_split = split_once_outside_quotes(place, " of ", last=True)
        if field_split:
            field_name, owner_expr = field_split
            owner = self.eval_expression(owner_expr, env)
            self.set_field(owner, field_name, value)
        else:
            env.assign(place, value)
        return value

    def execute_if_chain(self, lines: list[Line], start_index: int, env: Environment) -> tuple[Any, int]:
        candidates: list[tuple[str | None, list[Line]]] = []
        first = lines[start_index]
        candidates.append((strip_prefix(first.text, "If "), first.children))
        index = start_index + 1
        while index < len(lines):
            text = lines[index].text
            if starts(text, "Otherwise if "):
                candidates.append((strip_prefix(text, "Otherwise if "), lines[index].children))
                index += 1
            elif text == "Otherwise":
                candidates.append((None, lines[index].children))
                index += 1
                break
            else:
                break
        for condition, children in candidates:
            if condition is None or self.truthy(self.eval_expression(condition, env)):
                return self.execute_block(children, env), index
        return None, index

    def execute_try(self, lines: list[Line], start_index: int, env: Environment) -> tuple[Any, int]:
        try_line = lines[start_index]
        catch_line: Line | None = None
        finally_line: Line | None = None
        index = start_index + 1
        if index < len(lines) and starts(lines[index].text, "Catch "):
            catch_line = lines[index]
            index += 1
        if index < len(lines) and lines[index].text == "Finally":
            finally_line = lines[index]
            index += 1
        value = None
        try:
            value = self.execute_block(try_line.children, env)
        except NeedStopped as stopped:
            if catch_line is None:
                raise
            catch_name = strip_prefix(catch_line.text, "Catch ")
            env.define(catch_name, stopped.value)
            value = self.execute_block(catch_line.children, env)
        finally:
            if finally_line is not None:
                self.execute_block(finally_line.children, env)
        return value, index

    def execute_repeat(self, line: Line, env: Environment) -> Any:
        text = line.text
        last_value = None
        if starts(text, "Repeat for "):
            header = strip_prefix(text, "Repeat for ")
            split = split_once_outside_quotes(header, " in ")
            if not split:
                raise PlainError(f"Line {line.number} needs the word in.")
            names_text, expression = split
            names = [name.strip() for name in split_outside_quotes(names_text, " and ")]
            values = self.eval_expression(expression, env)
            for value in list(values):
                self.bind_repeat_names(names, value, env)
                try:
                    last_value = self.execute_block(line.children, env)
                except SkipRepeat:
                    continue
                except StopRepeat:
                    break
            return last_value
        if starts(text, "Repeat while "):
            condition = strip_prefix(text, "Repeat while ")
            guard = 0
            while self.truthy(self.eval_expression(condition, env)):
                guard += 1
                if guard > 100000:
                    raise PlainError("This repeat ran too many times. Use Stop or change the condition.")
                try:
                    last_value = self.execute_block(line.children, env)
                except SkipRepeat:
                    continue
                except StopRepeat:
                    break
            return last_value
        if text == "Repeat forever":
            guard = 0
            while True:
                guard += 1
                if guard > 100000:
                    raise PlainError("This forever repeat ran too many times without Stop.")
                try:
                    last_value = self.execute_block(line.children, env)
                except SkipRepeat:
                    continue
                except StopRepeat:
                    break
            return last_value
        raise PlainError(f"Line {line.number} has a Repeat form I do not understand.")

    def bind_repeat_names(self, names: list[str], value: Any, env: Environment) -> None:
        self.bind_names(names, value, env)

    def bind_names(self, names: list[str], value: Any, env: Environment, constant: bool = False, type_name: str | None = None) -> None:
        if len(names) == 1:
            env.define(names[0], value, constant=constant, type_name=type_name)
            return
        pieces = self.destructure_value(names, value)
        for name, item in zip(names, pieces):
            env.define(name, item, constant=constant)

    def destructure_value(self, names: list[str], value: Any) -> list[Any]:
        if isinstance(value, Instance):
            items: list[Any] = []
            for name in names:
                key = normalize(name)
                self.ensure_field_visible(value, key, name)
                if key not in value.fields:
                    raise PlainError(f"{value.type_name} does not have {clean_name(name)} to destructure.")
                items.append(value.fields[key])
            return items
        if self.is_map_value(value):
            items = []
            for name in names:
                items.append(self.map_value_for_destructure(value, name))
            return items
        if isinstance(value, set):
            values = sorted(value, key=lambda item: (type(item).__name__, self.to_text(item)))
            self.ensure_destructure_count(names, values)
            return values
        if isinstance(value, (list, tuple)):
            values = list(value)
            self.ensure_destructure_count(names, values)
            return values
        raise PlainError(f"{self.to_text(value)} cannot be destructured.")

    def ensure_destructure_count(self, names: list[str], values: list[Any]) -> None:
        if len(values) != len(names):
            raise PlainError(f"Destructuring needs {len(names)} value(s), but it received {len(values)}.")

    def map_value_for_destructure(self, mapping: Any, name: str) -> Any:
        wanted = normalize(name)
        matches = [key for key in self.map_keys(mapping) if normalize(str(key)) == wanted]
        if len(matches) == 1:
            return self.map_get_value(mapping, matches[0])
        if len(matches) > 1:
            raise PlainError(f"Map has more than one key matching {clean_name(name)}.")
        raise PlainError(f"Map does not have {clean_name(name)} to destructure.")

    def execute_match(self, line: Line, env: Environment) -> Any:
        value = self.eval_expression(strip_prefix(line.text, "Match "), env)
        for child in line.children:
            if not starts(child.text, "When "):
                continue
            pattern = strip_prefix(child.text, "When ")
            matched, bindings = self.match_pattern(pattern, value, env)
            if matched:
                for name, item in bindings.items():
                    env.define(name, item)
                return self.execute_block(child.children, env)
        raise PlainError("This match did not handle the value it received.")

    def execute_expect(self, line: Line, env: Environment) -> bool:
        expression = strip_prefix(line.text, "Expect ")
        split = split_once_outside_quotes(expression, " is ")
        if not split:
            raise PlainError(f"Line {line.number} needs the word is in the expectation.")
        left_text, right_text = split
        left = self.eval_expression(left_text, env)
        right = self.eval_expression(right_text, env)
        if left != right:
            raise PlainError(f"Expected {left_text} to be {self.to_text(right)}, but it was {self.to_text(left)}.")
        return True

    def execute_send(self, text: str, env: Environment) -> Any:
        rest = strip_prefix(text, "Send ")
        split = split_once_outside_quotes(rest, " to ", last=True)
        if not split:
            raise PlainError("Send needs the word to.")
        value = self.eval_expression(split[0], env)
        target = self.eval_expression(split[1], env)
        if isinstance(target, Channel):
            return target.send(value)
        raise PlainError("Send can only send to a channel.")

    def execute_bring(self, target: str, env: Environment) -> Any:
        target = target.strip()
        alias = None
        alias_split = split_once_outside_quotes(target, " as ")
        if alias_split:
            target, alias = alias_split
        names: list[str] = []
        names_split = split_once_outside_quotes(target, " names ")
        if names_split:
            target, names_text = names_split
            names = [clean_name(item) for item in split_outside_quotes(names_text, " and ")]
        if starts(target, "Package "):
            package_target = strip_prefix(target, "Package ")
            if len(package_target) >= 2 and package_target[0] == '"' and package_target[-1] == '"':
                package_target = package_target[1:-1]
            module_path = self.resolve_package_path(package_target).resolve()
        elif len(target) >= 2 and target[0] == '"' and target[-1] == '"':
            module_path = self.resolve_path(target[1:-1]).resolve()
        elif target.lower().endswith(".271"):
            module_path = self.resolve_path(target).resolve()
        else:
            return None
        if module_path in self.loaded_modules and not alias and not names:
            return None
        if not module_path.exists():
            raise PlainError(f"Could not bring {module_path}. The file does not exist.")
        previous_base = self.base_dir
        try:
            self.base_dir = module_path.parent
            source = module_path.read_text(encoding="utf-8")
            if alias or names:
                module_env = Environment(parent=self.global_env, runner=self)
                self.execute_block(parse_program(source, source_label=str(module_path)), module_env)
                if alias:
                    env.define(alias, ModuleValue(clean_name(alias), dict(module_env.values)), constant=True)
                for name in names:
                    key = normalize(name)
                    if key not in module_env.values:
                        if key in self.types:
                            continue
                        raise PlainError(f"{module_path.name} does not contain {name}.")
                    env.define(name, module_env.values[key], constant=True)
            else:
                self.loaded_modules.add(module_path)
                self.execute(source, run_main=False, source_label=str(module_path))
        finally:
            self.base_dir = previous_base
        return None

    def resolve_package_path(self, target: str) -> Path:
        normalized = target.replace("\\", "/").strip("/")
        parts = normalized.split("/", 1)
        package_name = parts[0]
        inner = parts[1] if len(parts) > 1 else "main.271"
        candidates = [
            Path.cwd() / "packages" / package_name / inner,
            self.base_dir / "packages" / package_name / inner,
            self.base_dir / ".." / "packages" / package_name / inner,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise PlainError(f"Package file {target} is not installed. Use 271 add {package_name}.")

    def execute_type(self, text: str) -> None:
        split = split_once_outside_quotes(text, " means ")
        if split:
            self.aliases[normalize(split[0])] = split[1]

    def define_type(self, line: Line, env: Environment) -> None:
        text = line.text
        if starts(text, "Record "):
            rest = strip_prefix(text, "Record ")
            parent = None
            follows = split_once_outside_quotes(rest, " follows ")
            if follows:
                name, contract_text = follows
                contracts = [clean_name(item) for item in split_outside_quotes(contract_text, " and ")]
            else:
                name = rest
                contracts = []
        elif starts(text, "Problem "):
            name = strip_prefix(text, "Problem ")
            parent = None
            contracts = []
        else:
            rest = strip_prefix(text, "Object ")
            parent = None
            contracts = []
            extends = split_once_outside_quotes(rest, " extends ")
            follows = split_once_outside_quotes(rest, " follows ")
            if extends:
                name, parent = extends
            elif follows:
                name, contract_text = follows
                contracts = [clean_name(item) for item in split_outside_quotes(contract_text, " and ")]
            else:
                name = rest
        type_def = TypeDef(name=clean_name(name), parent=clean_name(parent) if parent else None, contracts=contracts)
        for child in line.children:
            child_text = child.text
            private_field = False
            private_method = False
            if starts(child_text, "Private Has "):
                child_text = strip_prefix(child_text, "Private ")
                private_field = True
            if starts(child_text, "Private Teach ") or starts(child_text, "Private Async Teach "):
                child_text = strip_prefix(child_text, "Private ")
                private_method = True
                child = Line(text=child_text, number=child.number, indent=child.indent, children=child.children, source=child.source)
            if starts(child_text, "Has "):
                field_text = strip_prefix(child_text, "Has ")
                field_name = split_once_outside_quotes(field_text, " as ")
                name_text = clean_name(field_name[0] if field_name else field_text)
                type_def.fields.append(name_text)
                if private_field:
                    type_def.private_fields.add(normalize(name_text))
                if field_name:
                    type_def.field_types[normalize(name_text)] = field_name[1]
            elif starts(child_text, "Async Teach "):
                teaching = self.make_teaching(child, env, async_prefix=True)
                teaching.owner_type = type_def.name
                type_def.methods[normalize(teaching.name)] = teaching
                if private_method:
                    type_def.private_methods.add(normalize(teaching.name))
            elif starts(child_text, "Teach "):
                teaching = self.make_teaching(child, env)
                teaching.owner_type = type_def.name
                type_def.methods[normalize(teaching.name)] = teaching
                if private_method:
                    type_def.private_methods.add(normalize(teaching.name))
        self.types[normalize(name)] = type_def
        self.verify_contracts(type_def)

    def define_contract(self, line: Line) -> None:
        name = clean_name(strip_prefix(line.text, "Contract "))
        required: list[str] = []
        for child in line.children:
            if starts(child.text, "Teach "):
                rest = strip_prefix(child.text, "Teach ")
                using = split_once_outside_quotes(rest, " using ")
                returns = split_once_outside_quotes(rest, " returns ")
                if using:
                    required.append(clean_name(using[0]))
                elif returns:
                    required.append(clean_name(returns[0]))
                else:
                    required.append(clean_name(rest))
        self.contracts[normalize(name)] = required

    def verify_contracts(self, type_def: TypeDef) -> None:
        available = set(type_def.methods.keys())
        if type_def.parent:
            parent = self.types.get(normalize(type_def.parent))
            if parent:
                available.update(parent.methods.keys())
        for contract in type_def.contracts:
            required = self.contracts.get(normalize(contract))
            if required is None:
                raise PlainError(f"{type_def.name} follows {contract}, but that contract has not been defined.")
            for method in required:
                if normalize(method) not in available:
                    raise PlainError(f"{type_def.name} follows {contract}, so it must teach {method}.")

    def define_teaching(self, line: Line, env: Environment, async_prefix: bool = False, test_prefix: bool = False) -> Teaching:
        teaching = self.make_teaching(line, env, async_prefix=async_prefix, test_prefix=test_prefix)
        env.define(teaching.name, teaching, constant=True)
        return teaching

    def make_teaching(self, line: Line, env: Environment, async_prefix: bool = False, test_prefix: bool = False) -> Teaching:
        text = line.text
        if starts(text, "Async Teach "):
            text = strip_prefix(text, "Async ")
        if starts(text, "Test Teach "):
            text = "Teach " + strip_prefix(text, "Test Teach ")
        rest = strip_prefix(text, "Teach ")
        returns = split_once_outside_quotes(rest, " returns ")
        if returns:
            rest = returns[0]
        using = split_once_outside_quotes(rest, " using ")
        if using:
            name, params_text = using
            params = parse_parameters(params_text)
        else:
            name = rest
            params = []
        return Teaching(name=clean_name(name), parameters=params, body=line.children, closure=env, runner=self, source=line.source, line_number=line.number)

    def eval_expression(self, expression: str, env: Environment) -> Any:
        expr = expression.strip()
        if not expr:
            return None
        annotated = split_once_outside_quotes(expr, " as ", last=True)
        if annotated and not starts(expr, "Use ") and not starts(expr, "New "):
            value = self.eval_expression(annotated[0], env)
            self.ensure_type(value, annotated[1], annotated[0])
            return self.apply_runtime_type(value, annotated[1])
        if starts(expr, "Need "):
            return self.need(self.eval_expression(strip_prefix(expr, "Need "), env))
        if starts(expr, "Await "):
            return self.await_value(self.eval_expression(strip_prefix(expr, "Await "), env))
        if starts(expr, "Spawn "):
            return self.spawn_expression(strip_prefix(expr, "Spawn "), env)
        if starts(expr, "Receive from "):
            target = self.eval_expression(strip_prefix(expr, "Receive from "), env)
            if isinstance(target, Channel):
                return target.receive()
            raise PlainError("Receive needs a channel.")
        if starts(expr, "Success "):
            return Result.success(self.eval_expression(strip_prefix(expr, "Success "), env))
        if starts(expr, "Failure "):
            return Result.failure(self.eval_expression(strip_prefix(expr, "Failure "), env))
        if starts(expr, "Ask"):
            prompt = strip_prefix(expr, "Ask").strip()
            label = self.eval_expression(prompt, env) if prompt else ""
            return input(f"{label}: " if label else "")
        if starts(expr, "Teach using "):
            return self.make_anonymous_teaching(expr, env)
        if starts(expr, "Use "):
            return self.eval_call(strip_prefix(expr, "Use "), env)
        if starts(expr, "New "):
            return self.eval_new(strip_prefix(expr, "New "), env)
        if starts(expr, "List with "):
            return [self.eval_expression(part, env) for part in split_outside_quotes(strip_prefix(expr, "List with "), " and ")]
        if expr == "Empty List":
            return []
        if starts(expr, "Set with "):
            return set(self.eval_expression(part, env) for part in split_outside_quotes(strip_prefix(expr, "Set with "), " and "))
        if expr == "Empty Set":
            return set()
        if starts(expr, "Tuple with "):
            return tuple(self.eval_expression(part, env) for part in split_outside_quotes(strip_prefix(expr, "Tuple with "), " and "))
        if starts(expr, "Map with "):
            return self.eval_map(strip_prefix(expr, "Map with "), env)
        if expr == "Empty Map":
            return MapValue()
        if starts(expr, "Range from "):
            return self.eval_range(expr, env)
        if starts(expr, "Some "):
            return self.eval_expression(strip_prefix(expr, "Some "), env)
        if expr == "nothing":
            return None
        if expr == "true":
            return True
        if expr == "false":
            return False
        if re.fullmatch(r"-?\d+", expr):
            return int(expr)
        if re.fullmatch(r"-?\d+\.\d+", expr):
            return float(expr)
        if len(expr) >= 2 and expr[0] == '"' and expr[-1] == '"':
            return self.eval_string(expr[1:-1], env)
        if starts(expr, "not "):
            return not self.truthy(self.eval_expression(strip_prefix(expr, "not "), env))

        for phrase, fn in [
            (" or ", lambda a, b: self.truthy(a) or self.truthy(b)),
            (" and ", lambda a, b: self.truthy(a) and self.truthy(b)),
        ]:
            split = split_once_outside_quotes(expr, phrase)
            if split:
                return fn(self.eval_expression(split[0], env), self.eval_expression(split[1], env))

        comparisons = [
            (" is at least ", lambda a, b: a >= b),
            (" is at most ", lambda a, b: a <= b),
            (" is greater than ", lambda a, b: a > b),
            (" is less than ", lambda a, b: a < b),
            (" is not ", lambda a, b: a != b),
            (" is in ", lambda a, b: a in b),
            (" is ", lambda a, b: a == b),
        ]
        for phrase, fn in comparisons:
            split = split_once_outside_quotes(expr, phrase)
            if split:
                return fn(self.eval_expression(split[0], env), self.eval_expression(split[1], env))

        arithmetic = [
            (" plus ", lambda a, b: a + b),
            (" minus ", lambda a, b: a - b),
            (" times ", lambda a, b: a * b),
            (" over ", self.checked_divide),
            (" remainder ", lambda a, b: a % b),
        ]
        for phrase, fn in arithmetic:
            split = split_once_outside_quotes(expr, phrase, last=True)
            if split:
                return fn(self.eval_expression(split[0], env), self.eval_expression(split[1], env))

        special = self.eval_special_access(expr, env)
        if special is not _MISSING:
            return special

        return env.get(expr)

    def eval_string(self, value: str, env: Environment) -> str:
        def replace(match: re.Match[str]) -> str:
            return self.to_text(self.eval_expression(match.group(1), env))
        return re.sub(r"\{([^{}]+)\}", replace, value)

    def eval_map(self, text: str, env: Environment) -> MapValue:
        result = MapValue()
        if not text:
            return result
        for piece in split_outside_quotes(text, " and "):
            split = split_once_outside_quotes(piece, " meaning ")
            if not split:
                raise PlainError("Map entries need the word meaning.")
            key = self.eval_expression(split[0], env)
            value = self.eval_expression(split[1], env)
            result[key] = value
        return result

    def eval_map_lines(self, lines: list[Line], env: Environment) -> MapValue:
        result = MapValue()
        for line in lines:
            split = split_once_outside_quotes(line.text, " meaning ")
            if not split:
                raise PlainError(f"Line {line.number} needs the word meaning in this map entry.")
            key = self.eval_expression(split[0], env)
            value = self.eval_expression(split[1], env)
            result[key] = value
        return result

    def eval_range(self, expr: str, env: Environment) -> list[int]:
        match = re.match(r"Range from (.+?) to (.+?)(?: step (.+))?$", expr)
        if not match:
            raise PlainError("A range must say Range from Start to End.")
        start_value = int(self.eval_expression(match.group(1), env))
        end_value = int(self.eval_expression(match.group(2), env))
        step_value = int(self.eval_expression(match.group(3), env)) if match.group(3) else 1
        if step_value == 0:
            raise PlainError("A range step cannot be zero.")
        stop = end_value + (1 if step_value > 0 else -1)
        return list(range(start_value, stop, step_value))

    def eval_call(self, text: str, env: Environment) -> Any:
        split = split_once_outside_quotes(text, " with ")
        target = split[0] if split else text
        args_text = split[1] if split else ""
        positional, named = self.parse_arguments(args_text, env)

        method_split = split_once_outside_quotes(target, " of ", last=True)
        if method_split:
            method_name, owner_expression = method_split
            owner = self.eval_expression(owner_expression, env)
            if starts(method_name, "Parent "):
                return self.call_parent_method(owner, strip_prefix(method_name, "Parent "), positional, named)
            return self.call_method(owner, method_name, positional, named)

        key = normalize(target)
        if key in self.builtins:
            return self.builtins[key](positional, named)
        value = env.get(target)
        if isinstance(value, Teaching):
            return value.call(positional, named)
        raise PlainError(f"{clean_name(target)} is not something I can use.")

    def parse_arguments(self, text: str, env: Environment) -> tuple[list[Any], dict[str, Any]]:
        positional: list[Any] = []
        named: dict[str, Any] = {}
        if not text:
            return positional, named
        for piece in split_arguments(text):
            split = split_once_outside_quotes(piece, " be ")
            if split:
                named[normalize(split[0])] = self.eval_expression(split[1], env)
            else:
                positional.append(self.eval_expression(piece, env))
        return positional, named

    def eval_new(self, text: str, env: Environment) -> Instance | list[Any]:
        if starts(text, "Channel of "):
            split = split_once_outside_quotes(text, " with ")
            type_text = strip_prefix(split[0] if split else text, "Channel of ")
            args_text = split[1] if split else ""
            _positional, named = self.parse_arguments(args_text, env)
            return Channel(capacity=int(named.get("capacity", 0)), item_type=clean_name(type_text), runner=self)
        split = split_once_outside_quotes(text, " with ")
        type_name = clean_name(split[0] if split else text)
        args_text = split[1] if split else ""
        _positional, named = self.parse_arguments(args_text, env)
        fields = {key: value for key, value in named.items()}
        type_def = self.types.get(normalize(type_name))
        if type_def:
            for field_key, expected_type in self.collect_field_types(type_def).items():
                if field_key in fields:
                    self.ensure_type(fields[field_key], expected_type, field_key)
                    fields[field_key] = self.apply_runtime_type(fields[field_key], expected_type)
        return Instance(type_name=type_name, fields=fields)

    def eval_special_access(self, expr: str, env: Environment) -> Any:
        if starts(expr, "Length of "):
            value = self.eval_expression(strip_prefix(expr, "Length of "), env)
            return len(value)
        if starts(expr, "Indices of "):
            value = self.eval_expression(strip_prefix(expr, "Indices of "), env)
            return list(range(len(value)))
        if starts(expr, "Indexed "):
            value = self.eval_expression(strip_prefix(expr, "Indexed "), env)
            return list(enumerate(value))
        item_match = re.match(r"Item (.+?) of (.+)$", expr)
        if item_match:
            index = self.eval_expression(item_match.group(1), env)
            value = self.eval_expression(item_match.group(2), env)
            try:
                return value[index]
            except (IndexError, KeyError, TypeError):
                return None
        query_match = re.match(r"Query (.+?) of (.+)$", expr)
        if query_match:
            key = self.eval_expression(query_match.group(1), env)
            value = self.eval_expression(query_match.group(2), env)
            if isinstance(value, Instance) and normalize(value.type_name) == "http request":
                query = value.fields.get("query", {})
                return query.get(str(key))
            return self.get_field(value, key)
        field_split = split_once_outside_quotes(expr, " of ", last=True)
        if field_split:
            field_name, owner_expression = field_split
            owner = self.eval_expression(owner_expression, env)
            return self.get_field(owner, field_name)
        return _MISSING

    def make_anonymous_teaching(self, expr: str, env: Environment) -> Teaching:
        rest = strip_prefix(expr, "Teach using ")
        split = split_once_outside_quotes(rest, " give ")
        if not split:
            raise PlainError("An anonymous teaching needs the word give.")
        params = parse_parameters(split[0])
        body = [Line(text=split[1], number=0, indent=0)]
        return Teaching(name="<anonymous>", parameters=params, body=body, closure=env, runner=self, source="anonymous teaching", line_number=0)

    def get_field(self, owner: Any, field_name: Any) -> Any:
        key = normalize(str(field_name))
        if isinstance(owner, Instance):
            self.ensure_field_visible(owner, key, str(field_name))
            if key in owner.fields:
                return owner.fields[key]
            type_def = self.types.get(normalize(owner.type_name))
            while type_def:
                if key in type_def.methods:
                    self.ensure_method_visible(type_def, key, str(field_name))
                    teaching = type_def.methods[key]
                    self.private_access_stack.append(normalize(teaching.owner_type or type_def.name))
                    try:
                        return teaching.call([], {}, self_value=owner)
                    finally:
                        self.private_access_stack.pop()
                type_def = self.types.get(normalize(type_def.parent)) if type_def.parent else None
            return None
        if isinstance(owner, ModuleValue):
            return owner.values.get(key)
        if isinstance(owner, Result):
            if key == "value":
                return owner.value
            if key == "ok":
                return owner.ok
        if self.is_map_value(owner):
            for candidate in [field_name, key, key.replace(" ", "_")]:
                if candidate in owner:
                    return self.map_get_value(owner, candidate)
            return None
        return getattr(owner, key.replace(" ", "_"), None)

    def set_field(self, owner: Any, field_name: str, value: Any) -> None:
        key = normalize(field_name)
        if isinstance(owner, Instance):
            self.ensure_field_visible(owner, key, field_name)
            type_def = self.types.get(normalize(owner.type_name))
            expected_type = self.collect_field_types(type_def).get(key) if type_def else None
            if expected_type:
                self.ensure_type(value, expected_type, field_name)
                value = self.apply_runtime_type(value, expected_type)
            owner.fields[key] = value
            return
        if self.is_map_value(owner):
            self.map_set_value(owner, key, value)
            return
        raise PlainError(f"I cannot change {clean_name(field_name)} here.")

    def call_method(self, owner: Any, method_name: str, positional: list[Any], named: dict[str, Any]) -> Any:
        key = normalize(method_name)
        if isinstance(owner, ModuleValue):
            value = owner.values.get(key)
            if isinstance(value, Teaching):
                return value.call(positional, named)
            if value is not None:
                return value
            raise PlainError(f"{owner.name} does not contain {clean_name(method_name)}.")
        if isinstance(owner, Instance):
            type_def = self.types.get(normalize(owner.type_name))
            while type_def:
                if key in type_def.methods:
                    self.ensure_method_visible(type_def, key, method_name)
                    teaching = type_def.methods[key]
                    self.private_access_stack.append(normalize(teaching.owner_type or type_def.name))
                    try:
                        return teaching.call(positional, named, self_value=owner)
                    finally:
                        self.private_access_stack.pop()
                type_def = self.types.get(normalize(type_def.parent)) if type_def.parent else None
        if key == "close" and isinstance(owner, Channel):
            owner.close()
            return None
        if key == "message":
            return self.to_text(owner)
        if key == "json":
            if isinstance(owner, Instance) and normalize(owner.type_name) == "http request":
                try:
                    return Result.success(self.to_language_value(json.loads(owner.fields.get("body", "") or "{}")))
                except json.JSONDecodeError as error:
                    return Result.failure(f"Request JSON could not be parsed: {error.msg}.")
            if isinstance(owner, Instance) and normalize(owner.type_name) == "http response value":
                try:
                    return Result.success(self.to_language_value(json.loads(owner.fields.get("text", "") or "null")))
                except json.JSONDecodeError as error:
                    return Result.failure(f"Response JSON could not be parsed: {error.msg}.")
            return Result.success(owner)
        if key == "text":
            if isinstance(owner, Instance) and normalize(owner.type_name) == "http response value":
                return owner.fields.get("text", "")
            return self.to_text(owner)
        raise PlainError(f"{self.to_text(owner)} does not know how to {clean_name(method_name)}.")

    def call_parent_method(self, owner: Any, method_name: str, positional: list[Any], named: dict[str, Any]) -> Any:
        if not isinstance(owner, Instance):
            raise PlainError("Parent can only be used with an object.")
        if not self.private_access_stack:
            raise PlainError("Parent can only be used inside an object teaching.")
        current_type_key = self.private_access_stack[-1]
        current_type = self.types.get(current_type_key)
        if current_type is None:
            raise PlainError("Parent can only be used inside an object teaching.")
        if not current_type.parent:
            raise PlainError(f"{current_type.name} has no parent to use.")
        if not self.value_has_type(owner, current_type.name):
            raise PlainError(f"Parent of {current_type.name} can only be used with {current_type.name}.")
        key = normalize(method_name)
        type_def = self.types.get(normalize(current_type.parent))
        while type_def:
            if key in type_def.methods:
                self.ensure_method_visible(type_def, key, method_name)
                teaching = type_def.methods[key]
                self.private_access_stack.append(normalize(teaching.owner_type or type_def.name))
                try:
                    return teaching.call(positional, named, self_value=owner)
                finally:
                    self.private_access_stack.pop()
            type_def = self.types.get(normalize(type_def.parent)) if type_def.parent else None
        raise PlainError(f"{current_type.parent} does not know how to {clean_name(method_name)}.")

    def private_declaring_type(self, type_name: str, field_key: str) -> str | None:
        type_def = self.types.get(normalize(type_name))
        while type_def:
            if field_key in type_def.private_fields:
                return normalize(type_def.name)
            type_def = self.types.get(normalize(type_def.parent)) if type_def.parent else None
        return None

    def ensure_field_visible(self, owner: Instance, field_key: str, display_name: str | None = None) -> None:
        declaring_type = self.private_declaring_type(owner.type_name, field_key)
        if declaring_type is None:
            return
        if declaring_type in self.private_access_stack:
            return
        raise PlainError(f"{clean_name(display_name or field_key)} of {owner.type_name} is private.")

    def ensure_method_visible(self, type_def: TypeDef, method_key: str, display_name: str | None = None) -> None:
        if method_key not in type_def.private_methods:
            return
        declaring_type = normalize(type_def.name)
        if declaring_type in self.private_access_stack:
            return
        raise PlainError(f"{clean_name(display_name or method_key)} of {type_def.name} is private.")

    def match_pattern(self, pattern: str, value: Any, env: Environment) -> tuple[bool, dict[str, Any]]:
        pattern = pattern.strip()
        if pattern == "anything":
            return True, {}
        http_pattern = re.match(r"Http (Get|Post) with Path be (.+)$", pattern)
        if http_pattern:
            if not isinstance(value, Instance) or normalize(value.type_name) != "http request":
                return False, {}
            expected_method = http_pattern.group(1).upper()
            expected_path = self.eval_expression(http_pattern.group(2), env)
            return value.fields.get("method") == expected_method and value.fields.get("path") == expected_path, {}
        if pattern == "nothing":
            return value is None, {}
        if starts(pattern, "Some "):
            if value is None:
                return False, {}
            return True, {strip_prefix(pattern, "Some "): value}
        if starts(pattern, "Success "):
            if isinstance(value, Result) and value.ok:
                return True, {strip_prefix(pattern, "Success "): value.value}
            return False, {}
        if starts(pattern, "Failure "):
            if isinstance(value, Result) and not value.ok:
                return True, {strip_prefix(pattern, "Failure "): value.value}
            return False, {}
        if starts(pattern, "Map with "):
            return self.match_map_pattern(strip_prefix(pattern, "Map with "), value, env)
        list_start = re.match(r"List starting with (.+?) and many (.+)$", pattern)
        if list_start:
            if not isinstance(value, list) or not value:
                return False, {}
            matched, bindings = self.match_subpattern(list_start.group(1), value[0], env)
            if not matched:
                return False, {}
            if not self.merge_bindings(bindings, {list_start.group(2): value[1:]}):
                return False, {}
            return True, bindings
        if starts(pattern, "List with "):
            wanted = split_outside_quotes(strip_prefix(pattern, "List with "), " and ")
            if not isinstance(value, list) or len(value) != len(wanted):
                return False, {}
            bindings: dict[str, Any] = {}
            for piece, item in zip(wanted, value):
                matched, piece_bindings = self.match_subpattern(piece, item, env)
                if not matched or not self.merge_bindings(bindings, piece_bindings):
                    return False, {}
            return True, bindings
        fielded = split_once_outside_quotes(pattern, " with ")
        if fielded:
            return self.match_field_pattern(fielded[0], fielded[1], value, env)
        named = split_once_outside_quotes(pattern, " named ")
        if named:
            type_name, bind_name = named
            if self.value_has_type(value, type_name):
                return True, {bind_name: value}
            return False, {}
        for primitive in ["Int", "Float", "String", "Bool"]:
            if pattern == primitive and self.value_has_type(value, primitive):
                return True, {}
        if normalize(pattern) in self.types and self.value_has_type(value, pattern):
            return True, {}
        try:
            literal = self.eval_expression(pattern, env)
            return literal == value, {}
        except PlainError:
            return False, {}

    def match_subpattern(self, pattern: str, value: Any, env: Environment) -> tuple[bool, dict[str, Any]]:
        pattern = pattern.strip()
        if self.is_binding_pattern(pattern):
            return True, {pattern: value}
        return self.match_pattern(pattern, value, env)

    def is_binding_pattern(self, pattern: str) -> bool:
        if not pattern:
            return False
        if pattern in {"anything", "nothing", "true", "false", "Int", "Float", "String", "Bool"} or normalize(pattern) in self.types:
            return False
        if re.fullmatch(r"-?\d+(?:\.\d+)?", pattern):
            return False
        if len(pattern) >= 2 and pattern[0] == '"' and pattern[-1] == '"':
            return False
        if any(starts(pattern, prefix) for prefix in ["Some ", "Success ", "Failure ", "List ", "Map ", "Http "]):
            return False
        if split_once_outside_quotes(pattern, " named ") or split_once_outside_quotes(pattern, " with "):
            return False
        return True

    def match_map_pattern(self, entries_text: str, value: Any, env: Environment) -> tuple[bool, dict[str, Any]]:
        if not self.is_map_value(value):
            return False, {}
        bindings: dict[str, Any] = {}
        for entry in split_outside_quotes(entries_text, " and "):
            split = split_once_outside_quotes(entry, " meaning ")
            if not split:
                raise PlainError("Map patterns need the word meaning.")
            key_value = self.eval_expression(split[0], env)
            item = self.pattern_map_value(value, key_value)
            if item is _MISSING:
                return False, {}
            matched, entry_bindings = self.match_subpattern(split[1], item, env)
            if not matched or not self.merge_bindings(bindings, entry_bindings):
                return False, {}
        return True, bindings

    def match_field_pattern(self, type_name: str, entries_text: str, value: Any, env: Environment) -> tuple[bool, dict[str, Any]]:
        if not self.value_has_type(value, type_name):
            return False, {}
        bindings: dict[str, Any] = {}
        for entry in split_outside_quotes(entries_text, " and "):
            split = split_once_outside_quotes(entry, " be ")
            if not split:
                raise PlainError("Field patterns need the word be.")
            field_name, subpattern = split
            item = self.pattern_field_value(value, field_name)
            if item is _MISSING:
                raise PlainError(f"{clean_name(type_name)} does not have {clean_name(field_name)} to match.")
            matched, field_bindings = self.match_subpattern(subpattern, item, env)
            if not matched or not self.merge_bindings(bindings, field_bindings):
                return False, {}
        return True, bindings

    def pattern_field_value(self, value: Any, field_name: str) -> Any:
        key = normalize(field_name)
        if isinstance(value, Instance):
            self.ensure_field_visible(value, key, field_name)
            return value.fields[key] if key in value.fields else _MISSING
        if self.is_map_value(value):
            return self.pattern_map_value(value, field_name)
        if isinstance(value, Result):
            if key == "value":
                return value.value
            if key == "ok":
                return value.ok
        return getattr(value, key.replace(" ", "_"), _MISSING)

    def pattern_map_value(self, mapping: Any, key_value: Any) -> Any:
        if key_value in mapping:
            return self.map_get_value(mapping, key_value)
        wanted = normalize(str(key_value))
        matches = [key for key in self.map_keys(mapping) if normalize(str(key)) == wanted]
        if len(matches) == 1:
            return self.map_get_value(mapping, matches[0])
        return _MISSING

    def merge_bindings(self, target: dict[str, Any], incoming: dict[str, Any]) -> bool:
        for name, value in incoming.items():
            if name in target and target[name] != value:
                return False
            target[name] = value
        return True

    def value_has_type(self, value: Any, type_name: str) -> bool:
        type_name = self.resolve_type_name(type_name)
        union = split_once_outside_quotes(type_name, " or ")
        if union:
            return self.value_has_type(value, union[0]) or self.value_has_type(value, union[1])
        key = normalize(type_name)
        if key == "int":
            return isinstance(value, int) and not isinstance(value, bool)
        if key == "float":
            return isinstance(value, float)
        if key == "string":
            return isinstance(value, str)
        if key == "bool":
            return isinstance(value, bool)
        if key == "byte":
            return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255
        if key == "anything":
            return True
        if key == "list":
            return isinstance(value, list)
        if key == "set":
            return isinstance(value, set)
        if key == "map":
            return self.is_map_value(value)
        if key == "tuple":
            return isinstance(value, tuple)
        if key == "result":
            return isinstance(value, Result)
        if key == "task":
            return isinstance(value, TaskHandle)
        if starts(type_name, "Maybe "):
            return value is None or self.value_has_type(value, strip_prefix(type_name, "Maybe "))
        if starts(type_name, "List of "):
            return isinstance(value, list) and all(self.value_has_type(item, strip_prefix(type_name, "List of ")) for item in value)
        if starts(type_name, "Set of "):
            return isinstance(value, set) and all(self.value_has_type(item, strip_prefix(type_name, "Set of ")) for item in value)
        if starts(type_name, "Map of "):
            split = split_once_outside_quotes(strip_prefix(type_name, "Map of "), " to ")
            if not split or not self.is_map_value(value):
                return False
            return all(self.value_has_type(k, split[0]) and self.value_has_type(v, split[1]) for k, v in self.map_items(value))
        if starts(type_name, "Tuple of "):
            pieces = split_outside_quotes(strip_prefix(type_name, "Tuple of "), " and ")
            return isinstance(value, tuple) and len(value) == len(pieces) and all(self.value_has_type(item, expected) for item, expected in zip(value, pieces))
        if starts(type_name, "Result of "):
            return isinstance(value, Result)
        if starts(type_name, "Channel of "):
            if not isinstance(value, Channel):
                return False
            expected = strip_prefix(type_name, "Channel of ")
            if not value.item_type:
                return True
            return self.type_name_matches(value.item_type, expected)
        if isinstance(value, Instance):
            current = normalize(value.type_name)
            while current:
                if current == key:
                    return True
                type_def = self.types.get(current)
                current = normalize(type_def.parent) if type_def and type_def.parent else ""
        return False

    def resolve_type_name(self, type_name: str) -> str:
        current = clean_name(type_name)
        seen: set[str] = set()
        while normalize(current) in self.aliases and normalize(current) not in seen:
            seen.add(normalize(current))
            current = self.aliases[normalize(current)]
        return current

    def type_name_matches(self, actual: str, expected: str) -> bool:
        actual = self.resolve_type_name(actual)
        expected = self.resolve_type_name(expected)
        if expected in {"Anything", "Any"} or actual in {"Anything", "Any"}:
            return True
        union = split_once_outside_quotes(expected, " or ")
        if union:
            return self.type_name_matches(actual, union[0]) or self.type_name_matches(actual, union[1])
        if starts(expected, "Maybe "):
            if starts(actual, "Maybe "):
                return self.type_name_matches(strip_prefix(actual, "Maybe "), strip_prefix(expected, "Maybe "))
            return actual == "Nothing" or self.type_name_matches(actual, strip_prefix(expected, "Maybe "))
        return normalize(actual) == normalize(expected)

    def ensure_type(self, value: Any, type_name: str, place: str) -> None:
        if not self.value_has_type(value, type_name):
            raise PlainError(f"{clean_name(place)} must be {clean_name(type_name)}, but it was {self.to_text(value)}.")

    def ensure_absence_is_explicit(self, value: Any, type_name: str | None, place: str) -> None:
        if value is not None:
            return
        if type_name and self.type_allows_absence(type_name):
            return
        raise PlainError(f"{clean_name(place)} needs a Maybe type because it is nothing.")

    def type_allows_absence(self, type_name: str) -> bool:
        resolved = self.resolve_type_name(type_name)
        if resolved in {"Anything", "Any"}:
            return True
        if starts(resolved, "Maybe "):
            return True
        union = split_once_outside_quotes(resolved, " or ")
        if union:
            return self.type_allows_absence(union[0]) or self.type_allows_absence(union[1])
        return False

    def collect_field_types(self, type_def: TypeDef) -> dict[str, str]:
        fields: dict[str, str] = {}
        if type_def.parent:
            parent = self.types.get(normalize(type_def.parent))
            if parent:
                fields.update(self.collect_field_types(parent))
        fields.update(type_def.field_types)
        return fields

    def need(self, value: Any) -> Any:
        if isinstance(value, Result):
            if value.ok:
                return value.value
            raise NeedStopped(value.value)
        return value

    def truthy(self, value: Any) -> bool:
        if not isinstance(value, bool):
            raise PlainError(f"A condition must be true or false, but it was {self.to_text(value)}.")
        return value

    def checked_divide(self, left: Any, right: Any) -> Any:
        if right == 0:
            raise PlainError("Cannot divide by zero.")
        return left / right

    def to_text(self, value: Any) -> str:
        if value is None:
            return "nothing"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, Result):
            label = "Success" if value.ok else "Failure"
            return f"{label} {self.to_text(value.value)}"
        if isinstance(value, TaskHandle):
            return f"Task {value.name}"
        if isinstance(value, Channel):
            return "Channel"
        if isinstance(value, Instance):
            fields = ", ".join(f"{name}: {self.to_text(item)}" for name, item in value.fields.items())
            return f"{value.type_name}({fields})"
        if isinstance(value, ModuleValue):
            return f"Module {value.name}"
        if isinstance(value, list):
            return "[" + ", ".join(self.to_text(item) for item in value) + "]"
        if isinstance(value, tuple):
            return "(" + ", ".join(self.to_text(item) for item in value) + ")"
        if isinstance(value, set):
            return "{" + ", ".join(sorted(self.to_text(item) for item in value)) + "}"
        if self.is_map_value(value):
            return "{" + ", ".join(f"{self.to_text(k)}: {self.to_text(v)}" for k, v in value.items()) + "}"
        if isinstance(value, time.struct_time):
            return time.strftime("%Y-%m-%d %H:%M:%S", value)
        return str(value)

    def spawn_expression(self, expression: str, env: Environment) -> TaskHandle:
        return TaskHandle(expression, lambda: self.eval_expression(expression, env))

    def await_value(self, value: Any) -> Any:
        if isinstance(value, TaskHandle):
            return value.await_result()
        return value

    def task_success_value(self, value: Any) -> Any:
        if isinstance(value, Result):
            if value.ok:
                return value.value
            raise NeedStopped(value.value)
        return value

    def async_items(self, args: list[Any]) -> list[Any]:
        if len(args) == 1 and isinstance(args[0], list):
            return list(args[0])
        return list(args)

    def async_failure(self, error: BaseException) -> Result:
        if isinstance(error, NeedStopped):
            return Result.failure(error.value)
        return Result.failure(str(error))

    def builtin_async_all(self, args: list[Any], named: dict[str, Any]) -> TaskHandle:
        items = self.async_items(args)
        def target() -> Result:
            values: list[Any] = []
            for item in items:
                try:
                    values.append(self.task_success_value(self.await_value(item)))
                except BaseException as error:
                    return self.async_failure(error)
            return Result.success(values)
        return TaskHandle("Async All", target)

    def builtin_async_race(self, args: list[Any], named: dict[str, Any]) -> TaskHandle:
        items = self.async_items(args)
        if not items:
            return TaskHandle("Async Race", lambda: Result.failure("Async Race needs at least one task."))
        def target() -> Result:
            pending = list(items)
            while pending:
                for item in list(pending):
                    if isinstance(item, TaskHandle) and not item.is_done():
                        continue
                    try:
                        return Result.success(self.task_success_value(self.await_value(item)))
                    except BaseException as error:
                        return self.async_failure(error)
                time.sleep(0.001)
            return Result.failure("Async Race needs at least one task.")
        return TaskHandle("Async Race", target)

    def to_jsonable(self, value: Any) -> Any:
        if isinstance(value, Instance):
            return {key.replace(" ", "_"): self.to_jsonable(item) for key, item in value.fields.items()}
        if isinstance(value, Result):
            return {"ok": value.ok, "value": self.to_jsonable(value.value)}
        if isinstance(value, (list, tuple)):
            return [self.to_jsonable(item) for item in value]
        if isinstance(value, set):
            return [self.to_jsonable(item) for item in sorted(value, key=str)]
        if self.is_map_value(value):
            return {str(key): self.to_jsonable(item) for key, item in value.items()}
        if isinstance(value, time.struct_time):
            return time.strftime("%Y-%m-%d %H:%M:%S", value)
        return value

    def builtin_list_add(self, args: list[Any], named: dict[str, Any]) -> Any:
        if isinstance(args[0], TypedList) and args[0].item_type:
            self.ensure_type(args[1], args[0].item_type, "List item")
        args[0].append(args[1])
        return args[0]

    def builtin_list_replace_at(self, args: list[Any], named: dict[str, Any]) -> Any:
        if isinstance(args[0], TypedList) and args[0].item_type:
            self.ensure_type(args[2], args[0].item_type, "List item")
        args[0][int(args[1])] = args[2]
        return args[0]

    def builtin_set_add(self, args: list[Any], named: dict[str, Any]) -> Any:
        if isinstance(args[0], TypedSet) and args[0].item_type:
            self.ensure_type(args[1], args[0].item_type, "Set item")
        args[0].add(args[1])
        return args[0]

    def builtin_list_map(self, args: list[Any], named: dict[str, Any]) -> list[Any]:
        items, teaching = args[0], args[1]
        return [teaching.call([item], {}) for item in items]

    def builtin_list_filter(self, args: list[Any], named: dict[str, Any]) -> list[Any]:
        items, teaching = args[0], args[1]
        return [item for item in items if teaching.call([item], {})]

    def builtin_list_reduce(self, args: list[Any], named: dict[str, Any]) -> Any:
        items, total, teaching = args[0], args[1], args[2]
        for item in items:
            total = teaching.call([total, item], {})
        return total

    def builtin_list_sort(self, args: list[Any], named: dict[str, Any]) -> list[Any]:
        items = list(args[0])
        teaching = named.get("by")
        if isinstance(teaching, Teaching):
            return sorted(items, key=lambda item: teaching.call([item], {}))
        return sorted(items)

    def builtin_map_has(self, args: list[Any], named: dict[str, Any]) -> bool:
        if not self.is_map_value(args[0]):
            raise PlainError("Map Has needs a map.")
        try:
            return args[1] in args[0]
        except TypeError:
            raise PlainError("This Python-backed map cannot use that key. Use a 271 map value.")

    def builtin_map_get(self, args: list[Any], named: dict[str, Any]) -> Any:
        default = named.get("otherwise", args[2] if len(args) > 2 else None)
        return self.map_get_value(args[0], args[1], default)

    def builtin_map_put(self, args: list[Any], named: dict[str, Any]) -> Any:
        self.map_set_value(args[0], args[1], args[2])
        return args[0]

    def builtin_map_remove(self, args: list[Any], named: dict[str, Any]) -> Any:
        mapping = args[0]
        key = args[1]
        if isinstance(mapping, MapValue):
            mapping.pop(key, None)
            return mapping
        if isinstance(mapping, dict):
            try:
                mapping.pop(key, None)
                return mapping
            except TypeError:
                return mapping
        raise PlainError("Map Remove needs a map.")

    def builtin_map_merge(self, args: list[Any], named: dict[str, Any]) -> MapValue:
        if isinstance(args[0], MapValue):
            merged = MapValue(self.map_items(args[0]), key_type=args[0].key_type, value_type=args[0].value_type, runner=args[0].runner or self)
        else:
            merged = MapValue(self.map_items(args[0]))
        merged.update(args[1])
        return merged

    def builtin_map_keys(self, args: list[Any], named: dict[str, Any]) -> list[Any]:
        return [key for key, _item in self.map_items(args[0])]

    def builtin_map_values(self, args: list[Any], named: dict[str, Any]) -> list[Any]:
        return [item for _key, item in self.map_items(args[0])]

    def builtin_map_entries(self, args: list[Any], named: dict[str, Any]) -> list[tuple[Any, Any]]:
        return self.map_items(args[0])

    def builtin_int_parse(self, args: list[Any], named: dict[str, Any]) -> Result:
        try:
            return Result.success(int(str(args[0])))
        except ValueError:
            return Result.failure(f"{args[0]} is not an integer.")

    def builtin_float_parse(self, args: list[Any], named: dict[str, Any]) -> Result:
        try:
            return Result.success(float(str(args[0])))
        except ValueError:
            return Result.failure(f"{args[0]} is not a number.")

    def builtin_file_read(self, args: list[Any], named: dict[str, Any]) -> Result:
        path = self.resolve_path(args[0])
        try:
            return Result.success(path.read_text(encoding="utf-8"))
        except OSError as error:
            return Result.failure(str(error))

    def builtin_file_write(self, args: list[Any], named: dict[str, Any]) -> Result:
        path = self.resolve_path(args[0])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(args[1]), encoding="utf-8")
            return Result.success("written")
        except OSError as error:
            return Result.failure(str(error))

    def builtin_file_delete(self, args: list[Any], named: dict[str, Any]) -> Result:
        path = self.resolve_path(args[0])
        try:
            path.unlink()
            return Result.success("deleted")
        except OSError as error:
            return Result.failure(str(error))

    def builtin_file_walk(self, args: list[Any], named: dict[str, Any]) -> list[Instance]:
        path = self.resolve_path(args[0])
        return [Instance("File Entry", {"path": str(item)}) for item in path.rglob("*")]

    def builtin_json_parse(self, args: list[Any], named: dict[str, Any]) -> Result:
        try:
            return Result.success(self.to_language_value(json.loads(str(args[0]))))
        except json.JSONDecodeError as error:
            return Result.failure(f"JSON could not be parsed: {error.msg}.")

    def builtin_regex_match(self, args: list[Any], named: dict[str, Any]) -> bool:
        if not args:
            raise PlainError("Regex Match needs text.")
        pattern = named.get("pattern", args[1] if len(args) > 1 else None)
        if pattern is None:
            raise PlainError("Regex Match needs Pattern.")
        return re.search(str(pattern), str(args[0])) is not None

    def builtin_regex_replace(self, args: list[Any], named: dict[str, Any]) -> str:
        if not args:
            raise PlainError("Regex Replace needs text.")
        pattern = named.get("pattern", args[1] if len(args) > 1 else None)
        if pattern is None:
            raise PlainError("Regex Replace needs Pattern.")
        replacement = named.get("with", args[2] if len(args) > 2 else "")
        return re.sub(str(pattern), str(replacement), str(args[0]))

    def builtin_time_format(self, args: list[Any], named: dict[str, Any]) -> str:
        value = args[0]
        pattern = str(args[1] if len(args) > 1 else "%Y-%m-%d")
        replacements = {
            "yyyy": "%Y",
            "mm": "%m",
            "dd": "%d",
            "hh": "%H",
            "ss": "%S",
        }
        for plain, native in replacements.items():
            pattern = pattern.replace(plain, native)
        return time.strftime(pattern, value)

    def builtin_http_get(self, args: list[Any], named: dict[str, Any]) -> Result:
        return self.http_request("GET", str(args[0]), None)

    def builtin_http_post(self, args: list[Any], named: dict[str, Any]) -> Result:
        body: bytes | None = None
        headers: dict[str, str] = {}
        if "json" in named:
            body = json.dumps(self.to_jsonable(named["json"])).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif "text" in named:
            body = str(named["text"]).encode("utf-8")
            headers["Content-Type"] = "text/plain"
        elif len(args) > 1:
            body = str(args[1]).encode("utf-8")
        return self.http_request("POST", str(args[0]), body, headers=headers)

    def http_request(self, method: str, url: str, body: bytes | None, headers: dict[str, str] | None = None) -> Result:
        request = url_request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with url_request.urlopen(request, timeout=10) as response:
                text = response.read().decode("utf-8")
                value = Instance("Http Response Value", {
                    "status": response.status,
                    "text": text,
                    "headers": dict(response.headers.items()),
                })
                return Result.success(value)
        except url_error.HTTPError as error:
            text = error.read().decode("utf-8", errors="replace")
            value = Instance("Http Response Value", {
                "status": error.code,
                "text": text,
                "headers": dict(error.headers.items()) if error.headers else {},
            })
            return Result.failure(value)
        except (OSError, ValueError) as error:
            return Result.failure(f"HTTP {method} failed: {error}")

    def builtin_http_serve(self, args: list[Any], named: dict[str, Any]) -> None:
        port = int(named.get("port", args[0] if args else 2710))
        handle = named.get("handle", args[1] if len(args) > 1 else None)
        if not isinstance(handle, Teaching):
            raise PlainError("Http Serve needs Handle to be a teaching.")

        runner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.handle_request("GET")

            def do_POST(self) -> None:
                self.handle_request("POST")

            def log_message(self, format: str, *args: Any) -> None:
                return

            def handle_request(self, method: str) -> None:
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8") if length else ""
                query = {key: values[0] if values else "" for key, values in parse_qs(parsed.query).items()}
                request = Instance("Http Request", {
                    "method": method,
                    "path": parsed.path,
                    "query": query,
                    "body": body,
                })
                try:
                    response = handle.call([request], {})
                    status, content, content_type = runner.make_http_response(response)
                except Exception as error:
                    status, content, content_type = 500, f"Plain English error: {error}".encode("utf-8"), "text/plain"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        print(f"Serving twohundredseventyone on http://127.0.0.1:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Server stopped.")
        return None

    def make_http_response(self, response: Any) -> tuple[int, bytes, str]:
        if self.is_map_value(response):
            status = int(response.get("status") or 200)
            if response.get("json") is not None:
                return status, json.dumps(self.to_jsonable(response.get("json"))).encode("utf-8"), "application/json"
            text = response.get("text")
            return status, str(text if text is not None else "").encode("utf-8"), "text/plain"
        return 200, self.to_text(response).encode("utf-8"), "text/plain"


class Missing:
    pass


_MISSING = Missing()


def parse_parameters(text: str) -> list[Parameter]:
    parameters: list[Parameter] = []
    for piece in split_outside_quotes(text, " and "):
        variadic = False
        if starts(piece, "many "):
            variadic = True
            piece = strip_prefix(piece, "many ")
        default = None
        split_default = split_once_outside_quotes(piece, " be ")
        if split_default:
            piece, default = split_default
        split_type = split_once_outside_quotes(piece, " as ")
        name = split_type[0] if split_type else piece
        type_name = split_type[1] if split_type else None
        parameters.append(Parameter(name=clean_name(name), type_name=type_name, default=default, variadic=variadic))
    return parameters


def split_arguments(text: str) -> list[str]:
    raw = split_outside_quotes(text, " and ")
    pieces: list[str] = []
    index = 0
    while index < len(raw):
        current = raw[index]
        if "Teach using " in current and " give " not in current:
            combined = current
            index += 1
            while index < len(raw):
                combined += " and " + raw[index]
                if " give " in raw[index]:
                    break
                index += 1
            pieces.append(combined)
            index += 1
            continue
        pieces.append(current)
        index += 1
    return pieces


def run_file(path: Path, extra_args: list[str]) -> int:
    try:
        source = path.read_text(encoding="utf-8")
        diagnostics = check_source(source, str(path), base_dir=path.parent)
        if diagnostics:
            for diagnostic in diagnostics:
                line = diagnostic["range"]["start"]["line"] + 1
                print(f"Plain English error: {path} line {line}: {diagnostic['message']}", file=sys.stderr)
            return 1
        runner = Runner(argv=extra_args, base_dir=path.parent)
        runner.execute(source, source_label=str(path))
        return 0
    except PlainError as error:
        print(format_plain_error(error), file=sys.stderr)
        return 1
    except NeedStopped as stopped:
        print(f"Plain English error: Needed work failed with {stopped.value}.", file=sys.stderr)
        return 1


def run_tests(path: Path) -> int:
    test_files = sorted(path.rglob("*.271")) if path.is_dir() else [path]
    failures = 0
    for test_file in test_files:
        print(f"Testing {test_file}")
        code = run_file(test_file, [])
        if code != 0:
            failures += 1
    if failures:
        print(f"{failures} test file failed.")
        return 1
    print(f"All {len(test_files)} test file(s) passed.")
    return 0


def format_plain_error(error: PlainError) -> str:
    lines = [f"Plain English error: {error}"]
    if error.frames:
        lines.append("Trace:")
        for source, line, text in error.frames:
            location = f"{source} line {line}" if line else source
            lines.append(f"  at {location}: {text}")
    return "\n".join(lines)


def repl() -> int:
    print("twohundredseventyone REPL. Type Stop to leave.")
    runner = Runner()
    while True:
        try:
            line = input("271> ")
        except EOFError:
            print()
            break
        if line.strip() == "Stop":
            break
        try:
            runner.execute(line)
        except PlainError as error:
            print(format_plain_error(error))
    return 0


OLD_SYNTAX_PATTERNS = [
    (re.compile(r"^\s*let\b", re.IGNORECASE), "Use Make instead of let."),
    (re.compile(r"^\s*function\b", re.IGNORECASE), "Use Teach instead of function."),
    (re.compile(r"^\s*struct\b", re.IGNORECASE), "Use Record instead of struct."),
    (re.compile(r"^\s*class\b", re.IGNORECASE), "Use Object instead of class."),
    (re.compile(r"^\s*import\b", re.IGNORECASE), "Use Bring instead of import."),
    (re.compile(r"^\s*for\b", re.IGNORECASE), "Use Repeat for instead of for."),
    (re.compile(r"^\s*while\b", re.IGNORECASE), "Use Repeat while instead of while."),
    (re.compile(r"^\s*loop\b", re.IGNORECASE), "Use Repeat forever instead of loop."),
]


def language_files(path: Path) -> list[Path]:
    return sorted(path.rglob("*.271")) if path.is_dir() else [path]


def format_path(path: Path) -> int:
    for file in language_files(path):
        format_file(file)
        print(f"Formatted {file}.")
    return 0


def format_file(path: Path) -> int:
    source = path.read_text(encoding="utf-8")
    path.write_text(format_source(source), encoding="utf-8")
    return 0


def lint_path(path: Path) -> int:
    if not path.exists():
        print(f"Plain English error: Could not lint {path}. The path does not exist.", file=sys.stderr)
        return 1
    files = language_files(path)
    failures = 0
    for file in files:
        if lint_file(file) != 0:
            failures += 1
    if failures:
        print(f"{failures} file(s) need attention.", file=sys.stderr)
        return 1
    print(f"All {len(files)} file(s) look readable.")
    return 0


def lint_file(path: Path) -> int:
    try:
        source = path.read_text(encoding="utf-8")
        parse_program(source)
        for number, raw_line in enumerate(source.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("Note"):
                continue
            for pattern, message in OLD_SYNTAX_PATTERNS:
                if pattern.search(raw_line):
                    raise PlainError(f"{path} line {number}: {message}")
            if stripped.endswith(";"):
                raise PlainError(f"{path} line {number}: Lines do not end with semicolons.")
            if "{" in stripped and not stripped.startswith("Say ") and not stripped.startswith("Make "):
                pass
        print(f"{path} looks readable.")
        return 0
    except PlainError as error:
        print(format_plain_error(error), file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"Skipped {path} because it disappeared before lint could read it.")
        return 0


def lint_source(source: str, label: str = "document") -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    try:
        parse_program(source)
    except PlainError as error:
        diagnostics.append(make_diagnostic(1, 1, str(error)))
        return diagnostics
    for number, raw_line in enumerate(source.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("Note"):
            continue
        for pattern, message in OLD_SYNTAX_PATTERNS:
            if pattern.search(raw_line):
                diagnostics.append(make_diagnostic(number, 1, message))
        if stripped.endswith(";"):
            diagnostics.append(make_diagnostic(number, len(raw_line), "Lines do not end with semicolons."))
    return diagnostics


class CheckScope:
    def __init__(self, parent: "CheckScope | None" = None):
        self.parent = parent
        self.names: set[str] = set()
        self.constants: set[str] = set()
        self.types: set[str] = set()
        self.name_types: dict[str, str] = {}
        self.explicit_types: set[str] = set()
        self.private_access: set[str] = set(parent.private_access) if parent else set()
        self.current_type: str | None = parent.current_type if parent else None

    def child(self) -> "CheckScope":
        return CheckScope(self)

    def define(self, name: str, constant: bool = False, type_name: str | None = None, explicit_type: bool = False) -> None:
        key = normalize(name)
        self.names.add(key)
        if type_name:
            self.name_types[key] = type_name
        if type_name and explicit_type:
            self.explicit_types.add(key)
        if constant:
            self.constants.add(key)

    def define_type(self, name: str) -> None:
        self.types.add(normalize(name))

    def has_name(self, name: str) -> bool:
        key = normalize(name)
        if key in self.names:
            return True
        return self.parent.has_name(name) if self.parent else False

    def has_type(self, name: str) -> bool:
        key = normalize(name)
        if key in self.types:
            return True
        return self.parent.has_type(name) if self.parent else False

    def is_constant(self, name: str) -> bool:
        key = normalize(name)
        if key in self.constants:
            return True
        return self.parent.is_constant(name) if self.parent else False

    def get_type(self, name: str) -> str | None:
        key = normalize(name)
        if key in self.name_types:
            return self.name_types[key]
        return self.parent.get_type(name) if self.parent else None

    def has_explicit_type(self, name: str) -> bool:
        key = normalize(name)
        if key in self.explicit_types:
            return True
        return self.parent.has_explicit_type(name) if self.parent else False


class SemanticChecker:
    def __init__(self, label: str, base_dir: Path | None = None):
        self.label = label
        self.base_dir = base_dir or Path.cwd()
        self.diagnostics: list[dict[str, Any]] = []
        self.runner = Runner(base_dir=self.base_dir)
        self.builtins = set(self.runner.builtins.keys())
        self.loaded_exports: dict[Path, tuple[set[str], set[str]]] = {}
        self.type_aliases: dict[str, str] = {}
        self.type_field_names: dict[str, set[str]] = {}
        self.type_fields: dict[str, dict[str, str]] = {}
        self.type_methods: dict[str, set[str]] = {}
        self.type_method_parameters: dict[str, dict[str, list[Parameter]]] = {}
        self.type_method_returns: dict[str, dict[str, str]] = {}
        self.type_private_fields: dict[str, set[str]] = {}
        self.type_private_methods: dict[str, set[str]] = {}
        self.type_parents: dict[str, str] = {}
        self.signatures: dict[str, list[Parameter]] = {}

    def check(self, program: list[Line]) -> list[dict[str, Any]]:
        scope = CheckScope()
        scope.define("jew", constant=True, type_name="Int")
        for type_name in ["Int", "Float", "String", "Bool", "Byte", "Anything", "List", "Map", "Set", "Tuple", "Result", "Task"]:
            scope.define_type(type_name)
        self.check_block(program, scope, in_loop=False)
        return self.diagnostics

    def note(self, line: Line, message: str) -> None:
        self.diagnostics.append(make_diagnostic(line.number, 1, message))

    def make_expression_starts(self, text: str, prefix: str) -> bool:
        keyword = "Make " if starts(text, "Make ") else "Keep " if starts(text, "Keep ") else ""
        if not keyword:
            return False
        split = split_once_outside_quotes(strip_prefix(text, keyword), " be ")
        return bool(split and starts(split[1], prefix))

    def check_block(self, lines: list[Line], scope: CheckScope, in_loop: bool) -> None:
        index = 0
        while index < len(lines):
            line = lines[index]
            text = line.text
            if starts(text, "Otherwise") or starts(text, "Catch ") or text == "Finally":
                index += 1
                continue
            if starts(text, "If "):
                index = self.check_if_chain(lines, index, scope, in_loop)
                continue
            if starts(text, "Match "):
                self.check_match(line, scope, in_loop)
                index += 1
                continue
            if starts(text, "Repeat "):
                self.check_repeat(line, scope)
                index += 1
                continue
            if text == "Try":
                index = self.check_try(lines, index, scope, in_loop)
                continue
            if (starts(text, "Make ") or starts(text, "Keep ")) and self.make_expression_starts(text, "If "):
                index = self.check_make_if_chain(lines, index, scope, constant=starts(text, "Keep "), in_loop=in_loop)
                continue
            self.check_line(line, scope, in_loop)
            index += 1

    def check_line(self, line: Line, scope: CheckScope, in_loop: bool) -> None:
        text = line.text
        if starts(text, "Bring "):
            self.check_bring(line, scope)
            return
        if starts(text, "Type "):
            rest = strip_prefix(text, "Type ")
            split = split_once_outside_quotes(rest, " means ")
            if split:
                scope.define_type(split[0])
                self.type_aliases[normalize(split[0])] = split[1]
            return
        if starts(text, "Contract "):
            return
        if starts(text, "Record ") or starts(text, "Object ") or starts(text, "Problem "):
            self.check_type_definition(line, scope)
            return
        if starts(text, "Async Teach ") or starts(text, "Test Teach ") or starts(text, "Teach "):
            self.check_teaching(line, scope, define_name=not starts(text, "Teach using "))
            return
        if starts(text, "Make ") or starts(text, "Keep "):
            self.check_make(line, scope, constant=starts(text, "Keep "))
            return
        if starts(text, "Change "):
            self.check_change(line, scope)
            return
        if starts(text, "Say "):
            self.check_expression(strip_prefix(text, "Say "), line, scope)
            return
        if starts(text, "Expect "):
            expression = strip_prefix(text, "Expect ")
            split = split_once_outside_quotes(expression, " is ")
            if not split:
                self.note(line, "This expectation needs the word is.")
            else:
                self.check_expression(split[0], line, scope)
                self.check_expression(split[1], line, scope)
            return
        if starts(text, "Ignore Result "):
            expression = strip_prefix(text, "Ignore Result ")
            self.check_expression(expression, line, scope)
            inferred = self.infer_expression_type(expression, scope)
            if inferred and not self.type_is_result(inferred):
                self.note(line, "Ignore Result needs a Result value.")
            return
        if starts(text, "Need "):
            self.check_expression(strip_prefix(text, "Need "), line, scope)
            return
        if starts(text, "Await "):
            self.check_expression(strip_prefix(text, "Await "), line, scope)
            inferred = self.infer_expression_type(text, scope)
            if inferred and self.type_is_result(inferred):
                self.note(line, "This Result is ignored. Use Need, Match, Make, or Ignore Result.")
            return
        if starts(text, "Success ") or starts(text, "Failure "):
            self.check_expression(strip_prefix(text, text.split(" ", 1)[0] + " "), line, scope)
            return
        if starts(text, "Send "):
            rest = strip_prefix(text, "Send ")
            split = split_once_outside_quotes(rest, " to ", last=True)
            if not split:
                self.note(line, "Send needs the word to.")
            else:
                self.check_expression(split[0], line, scope)
                self.check_expression(split[1], line, scope)
                target_type = self.infer_expression_type(split[1], scope)
                message_type = self.infer_expression_type(split[0], scope)
                expected = self.channel_item_type_for_check(target_type)
                if expected and message_type and not self.type_matches(message_type, expected):
                    self.note(line, f"Channel message must be {expected}, but it is {message_type}.")
                elif target_type and not starts(self.resolve_check_type(target_type), "Channel"):
                    self.note(line, "Send can only send to a channel.")
            return
        if text in {"Stop", "Skip"}:
            if not in_loop:
                self.note(line, f"{text} can only be used inside Repeat.")
            return
        if text == "Map with":
            self.check_map_lines(line.children, line, scope)
            return
        if text:
            self.check_expression(text, line, scope)
            inferred = self.infer_expression_type(text, scope)
            if inferred and self.type_is_result(inferred):
                self.note(line, "This Result is ignored. Use Need, Match, Make, or Ignore Result.")

    def check_make(self, line: Line, scope: CheckScope, constant: bool) -> None:
        keyword = "Keep " if constant else "Make "
        split = split_once_outside_quotes(strip_prefix(line.text, keyword), " be ")
        if not split:
            self.note(line, "This line needs the word be.")
            return
        names_text, expression = split
        annotated = split_once_outside_quotes(expression, " as ", last=True)
        annotation = None
        if annotated:
            expression, annotation = annotated
        if expression == "Text":
            pass
        elif expression == "Map with":
            self.check_map_lines(line.children, line, scope)
        elif starts(expression, "If "):
            self.check_if_chain([Line(expression, line.number, line.indent, line.children, source=line.source)], 0, scope, in_loop=False)
        elif starts(expression, "Match "):
            self.check_match(Line(expression, line.number, line.indent, line.children, source=line.source), scope, in_loop=False)
        else:
            self.check_expression(expression, line, scope)
        inferred = self.infer_block_expression_type(expression, line, scope)
        if annotation and inferred and not self.type_matches(inferred, annotation):
            self.note(line, f"{clean_name(names_text)} must be {annotation}, but it is {inferred}.")
        if not annotation and inferred and self.type_may_be_absent(inferred):
            self.note(line, f"{clean_name(names_text)} may be nothing. Add as Maybe Type.")
        stored_type = annotation or inferred
        names = split_outside_quotes(names_text, " and ")
        stored_types = self.destructure_types_for_check(names, stored_type, expression, line, scope)
        for name, name_type in zip(names, stored_types):
            scope.define(name, constant=constant, type_name=name_type, explicit_type=bool(annotation))

    def check_make_if_chain(self, lines: list[Line], start_index: int, scope: CheckScope, constant: bool, in_loop: bool) -> int:
        line = lines[start_index]
        keyword = "Keep " if constant else "Make "
        split = split_once_outside_quotes(strip_prefix(line.text, keyword), " be ")
        if not split:
            self.note(line, "This line needs the word be.")
            return start_index + 1
        names_text, expression = split
        annotation = None
        annotated = split_once_outside_quotes(expression, " as ", last=True)
        if annotated:
            expression, annotation = annotated
        candidates: list[tuple[str | None, list[Line], Line]] = [(strip_prefix(expression, "If "), line.children, line)]
        index = start_index + 1
        while index < len(lines):
            text = lines[index].text
            if starts(text, "Otherwise if "):
                candidates.append((strip_prefix(text, "Otherwise if "), lines[index].children, lines[index]))
                index += 1
            elif text == "Otherwise":
                candidates.append((None, lines[index].children, lines[index]))
                index += 1
                break
            else:
                break
        branch_types: list[str] = []
        for condition, children, branch_line in candidates:
            if condition is not None:
                self.check_expression(condition, branch_line, scope)
            local = scope.child()
            self.check_block(children, local, in_loop)
            inferred = self.infer_block_type(children, local)
            if inferred:
                branch_types.append(inferred)
        inferred_type = self.common_type(branch_types)
        if annotation and inferred_type and not self.type_matches(inferred_type, annotation):
            self.note(line, f"{clean_name(names_text)} must be {annotation}, but it is {inferred_type}.")
        if not annotation and inferred_type and self.type_may_be_absent(inferred_type):
            self.note(line, f"{clean_name(names_text)} may be nothing. Add as Maybe Type.")
        names = split_outside_quotes(names_text, " and ")
        stored_type = annotation or inferred_type
        stored_types = self.destructure_types_for_check(names, stored_type, expression, line, scope)
        for name, name_type in zip(names, stored_types):
            scope.define(name, constant=constant, type_name=name_type, explicit_type=bool(annotation))
        return index

    def check_change(self, line: Line, scope: CheckScope) -> None:
        split = split_once_outside_quotes(strip_prefix(line.text, "Change "), " to ")
        if not split:
            self.note(line, "Change needs the word to.")
            return
        place, expression = split
        self.check_expression(expression, line, scope)
        field_split = split_once_outside_quotes(place, " of ", last=True)
        if field_split:
            self.check_expression(field_split[1], line, scope)
            owner_type = self.infer_expression_type(field_split[1], scope)
            self.check_private_field_access(owner_type, field_split[0], line, scope)
            if owner_type and self.field_names_known_for_check(owner_type) and not self.field_exists_for_check(owner_type, field_split[0]):
                self.note(line, f"{owner_type} does not have {clean_name(field_split[0])}.")
            expected = self.field_type_for_check(owner_type, field_split[0])
            inferred = self.infer_expression_type(expression, scope)
            if expected and inferred and not self.type_matches(inferred, expected):
                self.note(line, f"{clean_name(field_split[0])} must be {expected}, but it is {inferred}.")
            return
        if not scope.has_name(place):
            self.note(line, f"I do not know the name {clean_name(place)}.")
        elif scope.is_constant(place):
            self.note(line, f"{clean_name(place)} is kept and cannot be changed.")
        else:
            expected = scope.get_type(place)
            inferred = self.infer_expression_type(expression, scope)
            if expected and inferred and not self.type_matches(inferred, expected):
                self.note(line, f"{clean_name(place)} must be {expected}, but it is {inferred}.")

    def declared_return_type(self, text: str) -> str | None:
        if starts(text, "Private "):
            text = strip_prefix(text, "Private ")
        if starts(text, "Async Teach "):
            text = strip_prefix(text, "Async ")
        if starts(text, "Test Teach "):
            text = "Teach " + strip_prefix(text, "Test Teach ")
        if not starts(text, "Teach "):
            return None
        returns = split_once_outside_quotes(strip_prefix(text, "Teach "), " returns ")
        return returns[1] if returns else None

    def check_teaching(self, line: Line, scope: CheckScope, define_name: bool) -> None:
        text = line.text
        if starts(text, "Async Teach "):
            text = strip_prefix(text, "Async ")
        if starts(text, "Test Teach "):
            text = "Teach " + strip_prefix(text, "Test Teach ")
        if starts(text, "Teach using "):
            self.check_expression(text, line, scope)
            return
        rest = strip_prefix(text, "Teach ")
        return_type = None
        returns = split_once_outside_quotes(rest, " returns ")
        if returns:
            rest = returns[0]
            return_type = returns[1]
        using = split_once_outside_quotes(rest, " using ")
        name = using[0] if using else rest
        params_text = using[1] if using else ""
        if define_name:
            scope.define(name, constant=True)
            self.signatures[normalize(name)] = parse_parameters(params_text)
        local = scope.child()
        for parameter in parse_parameters(params_text):
            local.define(parameter.name, type_name=parameter.type_name, explicit_type=bool(parameter.type_name))
            if parameter.default is not None:
                self.check_expression(parameter.default, line, scope)
                inferred = self.infer_expression_type(parameter.default, scope)
                if parameter.type_name and inferred and not self.type_matches(inferred, parameter.type_name):
                    self.note(line, f"{parameter.name} must be {parameter.type_name}, but it is {inferred}.")
        self.check_block(line.children, local, in_loop=False)
        if return_type:
            inferred = self.infer_block_type(line.children, local)
            if inferred and not self.type_matches(inferred, return_type):
                self.note(line, f"{clean_name(name)} must return {return_type}, but it returns {inferred}.")

    def check_type_definition(self, line: Line, scope: CheckScope) -> None:
        text = line.text
        keyword = "Record " if starts(text, "Record ") else "Object " if starts(text, "Object ") else "Problem "
        name = strip_prefix(text, keyword)
        follows = split_once_outside_quotes(name, " follows ")
        if follows:
            name = follows[0]
        extends = split_once_outside_quotes(name, " extends ")
        if extends:
            name = extends[0]
            self.type_parents[normalize(name)] = clean_name(extends[1])
        scope.define_type(name)
        type_key = normalize(name)
        field_names: set[str] = set()
        fields: dict[str, str] = {}
        methods: set[str] = set()
        method_parameters: dict[str, list[Parameter]] = {}
        method_returns: dict[str, str] = {}
        private_fields: set[str] = set()
        private_methods: set[str] = set()
        for child in line.children:
            child_text = child.text
            if starts(child.text, "Has "):
                split = split_once_outside_quotes(strip_prefix(child.text, "Has "), " as ")
                field_names.add(normalize(split[0] if split else strip_prefix(child.text, "Has ")))
                if split:
                    fields[normalize(split[0])] = split[1]
            if starts(child.text, "Private Has "):
                split = split_once_outside_quotes(strip_prefix(child.text, "Private Has "), " as ")
                private_name = split[0] if split else strip_prefix(child.text, "Private Has ")
                field_names.add(normalize(private_name))
                private_fields.add(normalize(private_name))
                if split:
                    fields[normalize(private_name)] = split[1]
            private_method = False
            if starts(child_text, "Private Teach ") or starts(child_text, "Private Async Teach "):
                child_text = strip_prefix(child_text, "Private ")
                private_method = True
                child = Line(text=child_text, number=child.number, indent=child.indent, children=child.children, source=child.source)
            if starts(child_text, "Teach ") or starts(child_text, "Async Teach "):
                local = scope.child()
                local.define("Self", type_name=clean_name(name))
                local.current_type = clean_name(name)
                local.private_access.add(normalize(name))
                teaching = self.runner.make_teaching(child, self.runner.global_env)
                method_key = normalize(teaching.name)
                methods.add(method_key)
                method_parameters[method_key] = teaching.parameters
                return_type = self.declared_return_type(child_text)
                if return_type:
                    method_returns[method_key] = return_type
                if private_method:
                    private_methods.add(method_key)
                self.type_field_names[type_key] = field_names
                self.type_fields[type_key] = fields
                self.type_methods[type_key] = methods
                self.type_method_parameters[type_key] = method_parameters
                self.type_method_returns[type_key] = method_returns
                self.type_private_fields[type_key] = private_fields
                self.type_private_methods[type_key] = private_methods
                self.check_teaching(child, local, define_name=False)
        self.type_field_names[type_key] = field_names
        self.type_fields[type_key] = fields
        self.type_methods[type_key] = methods
        self.type_method_parameters[type_key] = method_parameters
        self.type_method_returns[type_key] = method_returns
        self.type_private_fields[type_key] = private_fields
        self.type_private_methods[type_key] = private_methods

    def check_if_chain(self, lines: list[Line], start_index: int, scope: CheckScope, in_loop: bool) -> int:
        first = lines[start_index]
        self.check_expression(strip_prefix(first.text, "If "), first, scope)
        self.check_block(first.children, scope.child(), in_loop)
        index = start_index + 1
        while index < len(lines):
            text = lines[index].text
            if starts(text, "Otherwise if "):
                self.check_expression(strip_prefix(text, "Otherwise if "), lines[index], scope)
                self.check_block(lines[index].children, scope.child(), in_loop)
                index += 1
            elif text == "Otherwise":
                self.check_block(lines[index].children, scope.child(), in_loop)
                index += 1
                break
            else:
                break
        return index

    def check_repeat(self, line: Line, scope: CheckScope) -> None:
        text = line.text
        if starts(text, "Repeat for "):
            split = split_once_outside_quotes(strip_prefix(text, "Repeat for "), " in ")
            if not split:
                self.note(line, "Repeat for needs the word in.")
                return
            names_text, expression = split
            self.check_expression(expression, line, scope)
            local = scope.child()
            for name in split_outside_quotes(names_text, " and "):
                local.define(name)
            self.check_block(line.children, local, in_loop=True)
            return
        if starts(text, "Repeat while "):
            self.check_expression(strip_prefix(text, "Repeat while "), line, scope)
            self.check_block(line.children, scope.child(), in_loop=True)
            return
        if text == "Repeat forever":
            self.check_block(line.children, scope.child(), in_loop=True)
            return
        self.note(line, "This Repeat form is not understood.")

    def check_try(self, lines: list[Line], start_index: int, scope: CheckScope, in_loop: bool) -> int:
        self.check_block(lines[start_index].children, scope.child(), in_loop)
        index = start_index + 1
        handled = False
        if index < len(lines) and starts(lines[index].text, "Catch "):
            local = scope.child()
            local.define(strip_prefix(lines[index].text, "Catch "))
            self.check_block(lines[index].children, local, in_loop)
            index += 1
            handled = True
        if index < len(lines) and lines[index].text == "Finally":
            self.check_block(lines[index].children, scope.child(), in_loop)
            index += 1
            handled = True
        if not handled:
            self.note(lines[start_index], "Try needs Catch or Finally.")
        return index

    def check_match(self, line: Line, scope: CheckScope, in_loop: bool) -> None:
        expression = strip_prefix(line.text, "Match ")
        self.check_expression(expression, line, scope)
        branches = [child for child in line.children if starts(child.text, "When ")]
        if not branches:
            self.note(line, "Match needs at least one When branch.")
            return
        for branch in branches:
            local = scope.child()
            self.bind_pattern_names(strip_prefix(branch.text, "When "), branch, local)
            self.check_block(branch.children, local, in_loop)
        self.check_union_match_exhaustive(expression, line, branches, scope)

    def check_union_match_exhaustive(self, expression: str, line: Line, branches: list[Line], scope: CheckScope) -> None:
        match_type = self.infer_expression_type(expression, scope)
        union_parts = self.union_parts_for_check(match_type)
        if len(union_parts) < 2:
            return
        covered: set[str] = set()
        for branch in branches:
            pattern = strip_prefix(branch.text, "When ")
            if pattern == "anything":
                return
            covered_type = self.pattern_type_for_union_check(pattern, scope)
            if not covered_type:
                continue
            for part in union_parts:
                if self.type_matches(covered_type, part):
                    covered.add(self.resolve_check_type(part))
        missing = [self.resolve_check_type(part) for part in union_parts if self.resolve_check_type(part) not in covered]
        if missing:
            self.note(line, f"Match on {clean_name(match_type or expression)} must handle {self.english_list(missing)} or use When anything.")

    def union_parts_for_check(self, type_name: str | None) -> list[str]:
        if not type_name:
            return []
        resolved = self.resolve_check_type(type_name)
        split = split_once_outside_quotes(resolved, " or ")
        if not split:
            return []
        parts: list[str] = []
        for piece in split:
            nested = self.union_parts_for_check(piece)
            if nested:
                parts.extend(nested)
            else:
                parts.append(self.resolve_check_type(piece))
        return parts

    def pattern_type_for_union_check(self, pattern: str, scope: CheckScope) -> str | None:
        pattern = pattern.strip()
        fielded = split_once_outside_quotes(pattern, " with ")
        if fielded:
            return clean_name(fielded[0])
        named = split_once_outside_quotes(pattern, " named ")
        if named:
            return clean_name(named[0])
        if pattern in {"Int", "Float", "String", "Bool"} or scope.has_type(pattern):
            return clean_name(pattern)
        return None

    def english_list(self, items: list[str]) -> str:
        clean = [clean_name(item) for item in items]
        if len(clean) <= 1:
            return clean[0] if clean else ""
        if len(clean) == 2:
            return f"{clean[0]} and {clean[1]}"
        return ", ".join(clean[:-1]) + f", and {clean[-1]}"

    def bind_pattern_names(self, pattern: str, line: Line, scope: CheckScope) -> None:
        if starts(pattern, "Some "):
            scope.define(strip_prefix(pattern, "Some "))
            return
        if starts(pattern, "Success "):
            scope.define(strip_prefix(pattern, "Success "))
            return
        if starts(pattern, "Failure "):
            scope.define(strip_prefix(pattern, "Failure "))
            return
        if starts(pattern, "Map with "):
            self.bind_map_pattern_names(strip_prefix(pattern, "Map with "), line, scope)
            return
        if starts(pattern, "List with "):
            for piece in split_outside_quotes(strip_prefix(pattern, "List with "), " and "):
                self.bind_pattern_names(piece, line, scope)
            return
        list_start = re.match(r"List starting with (.+?) and many (.+)$", pattern)
        if list_start:
            self.bind_pattern_names(list_start.group(1), line, scope)
            scope.define(list_start.group(2))
            return
        if starts(pattern, "Http "):
            return
        fielded = split_once_outside_quotes(pattern, " with ")
        if fielded:
            self.bind_field_pattern_names(fielded[0], fielded[1], line, scope)
            return
        named = split_once_outside_quotes(pattern, " named ")
        if named:
            scope.define(named[1])
            return
        if scope.has_type(pattern):
            return
        if self.is_binding_pattern_for_check(pattern, scope):
            scope.define(pattern)
            return
        if pattern not in {"anything", "nothing", "Int", "Float", "String", "Bool"} and not starts(pattern, "Http "):
            self.check_expression(pattern, line, scope)

    def bind_map_pattern_names(self, entries_text: str, line: Line, scope: CheckScope) -> None:
        for entry in split_outside_quotes(entries_text, " and "):
            split = split_once_outside_quotes(entry, " meaning ")
            if not split:
                self.note(line, "Map patterns need the word meaning.")
                continue
            self.check_expression(split[0], line, scope)
            self.bind_pattern_names(split[1], line, scope)

    def bind_field_pattern_names(self, type_name: str, entries_text: str, line: Line, scope: CheckScope) -> None:
        clean_type = clean_name(type_name)
        if not scope.has_type(clean_type) and clean_type not in {"Result", "Map"}:
            self.note(line, f"I do not know the type {clean_type}.")
        for entry in split_outside_quotes(entries_text, " and "):
            split = split_once_outside_quotes(entry, " be ")
            if not split:
                self.note(line, "Field patterns need the word be.")
                continue
            field_name, subpattern = split
            if self.field_names_known_for_check(clean_type):
                if not self.field_exists_for_check(clean_type, field_name):
                    self.note(line, f"{clean_type} does not have {clean_name(field_name)} to match.")
                self.check_private_field_access(clean_type, field_name, line, scope)
            self.bind_pattern_names(subpattern, line, scope)

    def is_binding_pattern_for_check(self, pattern: str, scope: CheckScope) -> bool:
        if not pattern:
            return False
        if pattern in {"anything", "nothing", "true", "false", "Int", "Float", "String", "Bool"} or scope.has_type(pattern):
            return False
        if self.is_literal(pattern):
            return False
        if any(starts(pattern, prefix) for prefix in ["Some ", "Success ", "Failure ", "List ", "Map ", "Http "]):
            return False
        if split_once_outside_quotes(pattern, " named ") or split_once_outside_quotes(pattern, " with "):
            return False
        return True

    def check_bring(self, line: Line, scope: CheckScope) -> None:
        target = strip_prefix(line.text, "Bring ").strip()
        alias = None
        alias_split = split_once_outside_quotes(target, " as ")
        if alias_split:
            target, alias = alias_split
        names: list[str] = []
        names_split = split_once_outside_quotes(target, " names ")
        if names_split:
            target, names_text = names_split
            names = [clean_name(item) for item in split_outside_quotes(names_text, " and ")]
        module_path: Path | None = None
        if starts(target, "Package "):
            package_target = strip_prefix(target, "Package ")
            if len(package_target) >= 2 and package_target[0] == '"' and package_target[-1] == '"':
                package_target = package_target[1:-1]
            module_path = self.resolve_package_for_check(package_target)
        elif len(target) >= 2 and target[0] == '"' and target[-1] == '"':
            module_path = self.base_dir / target[1:-1]
        elif target.lower().endswith(".271"):
            module_path = self.base_dir / target
        else:
            for name in names:
                scope.define(name, constant=True)
            return
        if alias:
            scope.define(alias, constant=True)
        if names:
            for name in names:
                scope.define(name, constant=True)
                scope.define_type(name)
        if module_path is None:
            return
        if not module_path.exists():
            self.note(line, f"Could not bring {module_path}. The file does not exist.")
            return
        exported_names, exported_types = self.module_exports(module_path)
        for type_name in exported_types:
            scope.define_type(type_name)
        if not alias and not names:
            for name in exported_names:
                scope.define(name, constant=True)

    def resolve_package_for_check(self, target: str) -> Path:
        normalized = target.replace("\\", "/").strip("/")
        parts = normalized.split("/", 1)
        package_name = parts[0]
        inner = parts[1] if len(parts) > 1 else "main.271"
        candidates = [
            Path.cwd() / "packages" / package_name / inner,
            self.base_dir / "packages" / package_name / inner,
            self.base_dir / ".." / "packages" / package_name / inner,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        return candidates[-1].resolve()

    def module_exports(self, path: Path) -> tuple[set[str], set[str]]:
        if path in self.loaded_exports:
            return self.loaded_exports[path]
        names: set[str] = set()
        types: set[str] = set()
        try:
            program = parse_program(path.read_text(encoding="utf-8"))
            for line in program:
                text = line.text
                if starts(text, "Teach "):
                    rest = strip_prefix(text, "Teach ")
                    returns = split_once_outside_quotes(rest, " returns ")
                    if returns:
                        rest = returns[0]
                    using = split_once_outside_quotes(rest, " using ")
                    names.add(clean_name(using[0] if using else rest))
                elif starts(text, "Record ") or starts(text, "Object ") or starts(text, "Problem "):
                    keyword = "Record " if starts(text, "Record ") else "Object " if starts(text, "Object ") else "Problem "
                    name = strip_prefix(text, keyword)
                    follows = split_once_outside_quotes(name, " follows ")
                    if follows:
                        name = follows[0]
                    extends = split_once_outside_quotes(name, " extends ")
                    if extends:
                        name = extends[0]
                    types.add(clean_name(name))
                elif starts(text, "Type "):
                    split = split_once_outside_quotes(strip_prefix(text, "Type "), " means ")
                    if split:
                        types.add(clean_name(split[0]))
                elif starts(text, "Make ") or starts(text, "Keep "):
                    keyword = "Make " if starts(text, "Make ") else "Keep "
                    split = split_once_outside_quotes(strip_prefix(text, keyword), " be ")
                    if split:
                        for name in split_outside_quotes(split[0], " and "):
                            names.add(clean_name(name))
        except (OSError, PlainError):
            pass
        self.loaded_exports[path] = (names, types)
        return names, types

    def check_expression(self, expression: str, line: Line, scope: CheckScope) -> None:
        expr = expression.strip()
        if not expr:
            return
        annotated = split_once_outside_quotes(expr, " as ", last=True)
        if annotated and not starts(expr, "Use ") and not starts(expr, "New "):
            self.check_expression(annotated[0], line, scope)
            inferred = self.infer_expression_type(annotated[0], scope)
            if inferred and not self.type_matches(inferred, annotated[1]):
                self.note(line, f"This value must be {annotated[1]}, but it is {inferred}.")
            return
        for prefix in ["Need ", "Await ", "Spawn ", "Some ", "Success ", "Failure "]:
            if starts(expr, prefix):
                self.check_expression(strip_prefix(expr, prefix), line, scope)
                return
        if starts(expr, "Receive from "):
            self.check_expression(strip_prefix(expr, "Receive from "), line, scope)
            return
        if starts(expr, "Ask"):
            prompt = strip_prefix(expr, "Ask").strip()
            if prompt:
                self.check_expression(prompt, line, scope)
            return
        if starts(expr, "Teach using "):
            self.check_anonymous_teaching(expr, line, scope)
            return
        if starts(expr, "Use "):
            self.check_call(strip_prefix(expr, "Use "), line, scope)
            return
        if starts(expr, "New "):
            self.check_new(strip_prefix(expr, "New "), line, scope)
            return
        if starts(expr, "List with ") or starts(expr, "Set with ") or starts(expr, "Tuple with "):
            prefix = "List with " if starts(expr, "List with ") else "Set with " if starts(expr, "Set with ") else "Tuple with "
            for part in split_outside_quotes(strip_prefix(expr, prefix), " and "):
                self.check_expression(part, line, scope)
            return
        if expr in {"Empty List", "Empty Set", "Empty Map", "nothing", "true", "false"} or self.is_literal(expr):
            return
        if expr == "Map with":
            self.note(line, "Map with needs indented entries or entries on the same line.")
            return
        if starts(expr, "Map with "):
            for piece in split_outside_quotes(strip_prefix(expr, "Map with "), " and "):
                split = split_once_outside_quotes(piece, " meaning ")
                if not split:
                    self.note(line, "Map entries need the word meaning.")
                else:
                    self.check_expression(split[0], line, scope)
                    self.check_expression(split[1], line, scope)
            return
        if starts(expr, "If "):
            self.note(line, "Expression-style If needs indented branches.")
            return
        if starts(expr, "Range from "):
            match = re.match(r"Range from (.+?) to (.+?)(?: step (.+))?$", expr)
            if not match:
                self.note(line, "A range must say Range from Start to End.")
            else:
                self.check_expression(match.group(1), line, scope)
                self.check_expression(match.group(2), line, scope)
                if match.group(3):
                    self.check_expression(match.group(3), line, scope)
            return
        if starts(expr, "Length of "):
            self.check_expression(strip_prefix(expr, "Length of "), line, scope)
            return
        if starts(expr, "Indices of "):
            self.check_expression(strip_prefix(expr, "Indices of "), line, scope)
            return
        if starts(expr, "Indexed "):
            self.check_expression(strip_prefix(expr, "Indexed "), line, scope)
            return
        for pattern in [r"Item (.+?) of (.+)$", r"Query (.+?) of (.+)$"]:
            match = re.match(pattern, expr)
            if match:
                self.check_expression(match.group(1), line, scope)
                self.check_expression(match.group(2), line, scope)
                return
        field_split = split_once_outside_quotes(expr, " of ", last=True)
        if field_split:
            self.check_expression(field_split[1], line, scope)
            owner_type = self.infer_expression_type(field_split[1], scope)
            self.check_private_field_access(owner_type, field_split[0], line, scope)
            self.check_private_method_access(owner_type, field_split[0], line, scope)
            return
        if starts(expr, "not "):
            self.check_expression(strip_prefix(expr, "not "), line, scope)
            return
        for phrase in [" or ", " and "]:
            split = split_once_outside_quotes(expr, phrase)
            if split:
                self.check_expression(split[0], line, scope)
                self.check_expression(split[1], line, scope)
                return
        for phrase in [" is at least ", " is at most ", " is greater than ", " is less than ", " is not ", " is in ", " is "]:
            split = split_once_outside_quotes(expr, phrase)
            if split:
                self.check_expression(split[0], line, scope)
                self.check_expression(split[1], line, scope)
                return
        for phrase in [" plus ", " minus ", " times ", " over ", " remainder "]:
            split = split_once_outside_quotes(expr, phrase, last=True)
            if split:
                self.check_expression(split[0], line, scope)
                self.check_expression(split[1], line, scope)
                return
        if not scope.has_name(expr):
            self.note(line, f"I do not know the name {clean_name(expr)}.")

    def check_map_lines(self, lines: list[Line], line: Line, scope: CheckScope) -> None:
        if not lines:
            self.note(line, "Map with needs at least one indented entry.")
            return
        for entry in lines:
            split = split_once_outside_quotes(entry.text, " meaning ")
            if not split:
                self.note(entry, "This map entry needs the word meaning.")
            else:
                self.check_expression(split[0], entry, scope)
                self.check_expression(split[1], entry, scope)

    def check_call(self, text: str, line: Line, scope: CheckScope) -> None:
        split = split_once_outside_quotes(text, " with ")
        target = split[0] if split else text
        args_text = split[1] if split else ""
        method_split = split_once_outside_quotes(target, " of ", last=True)
        if method_split:
            self.check_expression(method_split[1], line, scope)
            owner_type = self.infer_expression_type(method_split[1], scope)
            method_name = method_split[0]
            if starts(method_name, "Parent "):
                self.check_parent_method_call(owner_type, strip_prefix(method_name, "Parent "), line, scope)
            else:
                self.check_private_method_access(owner_type, method_name, line, scope)
        elif normalize(target) not in self.builtins and not scope.has_name(target):
            self.note(line, f"I do not know how to use {clean_name(target)}.")
        if args_text:
            pieces = split_arguments(args_text)
            for piece in pieces:
                named = split_once_outside_quotes(piece, " be ")
                self.check_expression(named[1] if named else piece, line, scope)
            self.check_collection_mutation_call(target, pieces, line, scope)
            if method_split:
                owner_type = self.infer_expression_type(method_split[1], scope)
                method_name = method_split[0]
                if starts(method_name, "Parent "):
                    current_parent = self.type_parents.get(normalize(scope.current_type or ""))
                    if current_parent:
                        self.check_method_argument_types(current_parent, strip_prefix(method_name, "Parent "), pieces, line, scope)
                else:
                    self.check_method_argument_types(owner_type, method_name, pieces, line, scope)
            else:
                self.check_call_argument_types(target, pieces, line, scope)

    def check_new(self, text: str, line: Line, scope: CheckScope) -> None:
        if starts(text, "Channel of "):
            split = split_once_outside_quotes(text, " with ")
            if split:
                for piece in split_arguments(split[1]):
                    named = split_once_outside_quotes(piece, " be ")
                    self.check_expression(named[1] if named else piece, line, scope)
            return
        split = split_once_outside_quotes(text, " with ")
        type_name = clean_name(split[0] if split else text)
        if not scope.has_type(type_name):
            self.note(line, f"I do not know the type {type_name}.")
        if split:
            for piece in split_arguments(split[1]):
                named = split_once_outside_quotes(piece, " be ")
                if named:
                    self.check_expression(named[1], line, scope)
                    expected = self.field_type_for_check(type_name, named[0])
                    inferred = self.infer_expression_type(named[1], scope)
                    if expected and inferred and not self.type_matches(inferred, expected):
                        self.note(line, f"{named[0]} must be {expected}, but it is {inferred}.")
                else:
                    self.check_expression(piece, line, scope)

    def check_anonymous_teaching(self, expr: str, line: Line, scope: CheckScope) -> None:
        split = split_once_outside_quotes(strip_prefix(expr, "Teach using "), " give ")
        if not split:
            self.note(line, "Anonymous teachings need the word give.")
            return
        params_text, body = split
        local = scope.child()
        for parameter in parse_parameters(params_text):
            local.define(parameter.name, type_name=parameter.type_name, explicit_type=bool(parameter.type_name))
            if parameter.default is not None:
                self.check_expression(parameter.default, line, scope)
        self.check_expression(body, line, local)

    def is_literal(self, expr: str) -> bool:
        if re.fullmatch(r"-?\d+(?:\.\d+)?", expr):
            return True
        if len(expr) >= 2 and expr[0] == '"' and expr[-1] == '"':
            return True
        return False

    def check_private_field_access(self, owner_type: str | None, field_name: str, line: Line, scope: CheckScope) -> None:
        if not owner_type:
            return
        declaring_type = self.private_declaring_check_type(owner_type, normalize(field_name))
        if declaring_type and declaring_type not in scope.private_access:
            self.note(line, f"{clean_name(field_name)} of {owner_type} is private.")

    def check_private_method_access(self, owner_type: str | None, method_name: str, line: Line, scope: CheckScope) -> None:
        if not owner_type:
            return
        declaring_type = self.private_method_declaring_check_type(owner_type, normalize(method_name))
        if declaring_type and declaring_type not in scope.private_access:
            self.note(line, f"{clean_name(method_name)} of {owner_type} is private.")

    def check_parent_method_call(self, owner_type: str | None, method_name: str, line: Line, scope: CheckScope) -> None:
        if not scope.current_type:
            self.note(line, "Parent can only be used inside an object teaching.")
            return
        parent = self.type_parents.get(normalize(scope.current_type))
        if not parent:
            self.note(line, f"{scope.current_type} has no parent to use.")
            return
        if owner_type and not self.type_matches(owner_type, scope.current_type):
            self.note(line, f"Parent of {scope.current_type} can only be used with {scope.current_type}.")
        parent_key = normalize(parent)
        if parent_key in self.type_methods and self.method_declaring_check_type(parent, normalize(method_name)) is None:
            self.note(line, f"{parent} does not know how to {clean_name(method_name)}.")
        self.check_private_method_access(parent, method_name, line, scope)

    def private_declaring_check_type(self, type_name: str, field_key: str) -> str | None:
        current = normalize(self.resolve_check_type(type_name))
        while current:
            if field_key in self.type_private_fields.get(current, set()):
                return current
            parent = self.type_parents.get(current)
            current = normalize(parent) if parent else ""
        return None

    def private_method_declaring_check_type(self, type_name: str, method_key: str) -> str | None:
        current = normalize(self.resolve_check_type(type_name))
        while current:
            if method_key in self.type_private_methods.get(current, set()):
                return current
            parent = self.type_parents.get(current)
            current = normalize(parent) if parent else ""
        return None

    def method_declaring_check_type(self, type_name: str, method_key: str) -> str | None:
        current = normalize(self.resolve_check_type(type_name))
        while current:
            if method_key in self.type_methods.get(current, set()):
                return current
            parent = self.type_parents.get(current)
            current = normalize(parent) if parent else ""
        return None

    def method_parameters_for_check(self, type_name: str | None, method_name: str) -> list[Parameter] | None:
        if not type_name:
            return None
        method_key = normalize(method_name)
        declaring_type = self.method_declaring_check_type(type_name, method_key)
        if not declaring_type:
            return None
        parameters = self.type_method_parameters.get(declaring_type, {}).get(method_key)
        if parameters and normalize(parameters[0].name) == "self":
            return parameters[1:]
        return parameters

    def method_return_type_for_check(self, type_name: str | None, method_name: str) -> str | None:
        if not type_name:
            return None
        method_key = normalize(method_name)
        declaring_type = self.method_declaring_check_type(type_name, method_key)
        if not declaring_type:
            return None
        return self.type_method_returns.get(declaring_type, {}).get(method_key)

    def item_access_type_for_check(self, owner_type: str | None) -> str | None:
        if not owner_type:
            return "Maybe Anything"
        resolved = self.resolve_check_type(owner_type)
        if starts(resolved, "List of "):
            return self.make_maybe_type(strip_prefix(resolved, "List of "))
        if starts(resolved, "Set of "):
            return self.make_maybe_type(strip_prefix(resolved, "Set of "))
        if starts(resolved, "Map of "):
            split = split_once_outside_quotes(strip_prefix(resolved, "Map of "), " to ")
            return self.make_maybe_type(split[1] if split else "Anything")
        if starts(resolved, "Tuple of "):
            item_type = self.common_type(split_outside_quotes(strip_prefix(resolved, "Tuple of "), " and "))
            return self.make_maybe_type(item_type or "Anything")
        if resolved == "String":
            return "Maybe String"
        if resolved in {"List", "Set", "Map", "Tuple", "Anything", "Any"}:
            return "Maybe Anything"
        return None

    def list_item_type_for_check(self, list_type: str | None) -> str | None:
        if not list_type:
            return None
        resolved = self.resolve_check_type(list_type)
        if starts(resolved, "List of "):
            return strip_prefix(resolved, "List of ")
        return None

    def set_item_type_for_check(self, set_type: str | None) -> str | None:
        if not set_type:
            return None
        resolved = self.resolve_check_type(set_type)
        if starts(resolved, "Set of "):
            return strip_prefix(resolved, "Set of ")
        return None

    def make_maybe_type(self, type_name: str) -> str:
        resolved = self.resolve_check_type(type_name)
        if starts(resolved, "Maybe "):
            return resolved
        if resolved == "Nothing":
            return "Maybe Anything"
        return f"Maybe {resolved}"

    def type_may_be_absent(self, type_name: str) -> bool:
        resolved = self.resolve_check_type(type_name)
        if resolved == "Nothing" or starts(resolved, "Maybe "):
            return True
        union = split_once_outside_quotes(resolved, " or ")
        if union:
            return self.type_may_be_absent(union[0]) or self.type_may_be_absent(union[1])
        return False

    def type_is_result(self, type_name: str) -> bool:
        resolved = self.resolve_check_type(type_name)
        if resolved == "Result" or starts(resolved, "Result of "):
            return True
        union = split_once_outside_quotes(resolved, " or ")
        if union:
            return self.type_is_result(union[0]) or self.type_is_result(union[1])
        return False

    def destructure_types_for_check(self, names: list[str], source_type: str | None, expression: str, line: Line, scope: CheckScope) -> list[str | None]:
        if len(names) == 1:
            return [source_type]
        literal_count = self.literal_group_count_for_check(expression, line)
        count_checked = literal_count is not None
        if literal_count is not None and literal_count != len(names):
            self.note(line, f"Destructuring needs {len(names)} value(s), but it received {literal_count}.")
        self.check_literal_map_destructure_names(names, expression, line, scope)
        if not source_type:
            return [None for _name in names]
        resolved = self.resolve_check_type(source_type)
        if starts(resolved, "Tuple of "):
            parts = split_outside_quotes(strip_prefix(resolved, "Tuple of "), " and ")
            if len(parts) != len(names) and not count_checked:
                self.note(line, f"Destructuring needs {len(names)} value(s), but it received {len(parts)}.")
            return [parts[index] if index < len(parts) else None for index in range(len(names))]
        if starts(resolved, "List of "):
            item_type = strip_prefix(resolved, "List of ")
            return [item_type for _name in names]
        if starts(resolved, "Set of "):
            item_type = strip_prefix(resolved, "Set of ")
            return [item_type for _name in names]
        if starts(resolved, "Map of "):
            split = split_once_outside_quotes(strip_prefix(resolved, "Map of "), " to ")
            return [split[1] if split else None for _name in names]
        if resolved in {"List", "Set", "Map", "Anything", "Any"}:
            return [None for _name in names]
        if self.field_names_known_for_check(resolved):
            types: list[str | None] = []
            for name in names:
                if not self.field_exists_for_check(resolved, name):
                    self.note(line, f"{resolved} does not have {clean_name(name)} to destructure.")
                    types.append(None)
                    continue
                self.check_private_field_access(resolved, name, line, scope)
                types.append(self.field_type_for_check(resolved, name))
            return types
        if resolved in {"Int", "Float", "String", "Bool", "Byte", "Nothing", "Result"}:
            self.note(line, f"{resolved} cannot be destructured.")
        return [None for _name in names]

    def literal_group_count_for_check(self, expression: str, line: Line) -> int | None:
        expr = expression.strip()
        if starts(expr, "Tuple with "):
            return len(split_outside_quotes(strip_prefix(expr, "Tuple with "), " and "))
        if starts(expr, "List with "):
            return len(split_outside_quotes(strip_prefix(expr, "List with "), " and "))
        if starts(expr, "Set with "):
            return len(split_outside_quotes(strip_prefix(expr, "Set with "), " and "))
        if expr in {"Empty List", "Empty Set"}:
            return 0
        if expr == "Map with" or starts(expr, "Map with "):
            return None
        return None

    def check_literal_map_destructure_names(self, names: list[str], expression: str, line: Line, scope: CheckScope) -> None:
        keys = self.literal_map_keys_for_check(expression, line, scope)
        if keys is None:
            return
        for name in names:
            if normalize(name) not in keys:
                self.note(line, f"Map does not have {clean_name(name)} to destructure.")

    def literal_map_keys_for_check(self, expression: str, line: Line, scope: CheckScope) -> set[str] | None:
        expr = expression.strip()
        entries: list[str] = []
        if expr == "Map with":
            entries = [child.text for child in line.children]
        elif starts(expr, "Map with "):
            entries = split_outside_quotes(strip_prefix(expr, "Map with "), " and ")
        else:
            return None
        keys: set[str] = set()
        for entry in entries:
            split = split_once_outside_quotes(entry, " meaning ")
            if not split:
                continue
            key_text = split[0].strip()
            if len(key_text) >= 2 and key_text[0] == '"' and key_text[-1] == '"':
                keys.add(normalize(key_text[1:-1]))
            else:
                inferred = self.infer_expression_type(key_text, scope)
                if inferred != "String":
                    return None
        return keys

    def field_names_known_for_check(self, type_name: str) -> bool:
        current = normalize(self.resolve_check_type(type_name))
        while current:
            if current in self.type_field_names:
                return True
            parent = self.type_parents.get(current)
            current = normalize(parent) if parent else ""
        return False

    def field_exists_for_check(self, type_name: str, field_name: str) -> bool:
        field_key = normalize(field_name)
        current = normalize(self.resolve_check_type(type_name))
        while current:
            if field_key in self.type_field_names.get(current, set()):
                return True
            parent = self.type_parents.get(current)
            current = normalize(parent) if parent else ""
        return False

    def field_type_for_check(self, type_name: str, field_name: str) -> str | None:
        field_key = normalize(field_name)
        current = normalize(self.resolve_check_type(type_name))
        while current:
            fields = self.type_fields.get(current, {})
            if field_key in fields:
                return fields[field_key]
            parent = self.type_parents.get(current)
            current = normalize(parent) if parent else ""
        return None

    def check_method_argument_types(self, owner_type: str | None, method_name: str, pieces: list[str], line: Line, scope: CheckScope) -> None:
        parameters = self.method_parameters_for_check(owner_type, method_name)
        if parameters is None:
            return
        self.check_parameters_against_arguments(parameters, pieces, line, scope)

    def check_call_argument_types(self, target: str, pieces: list[str], line: Line, scope: CheckScope) -> None:
        parameters = self.signatures.get(normalize(target))
        if not parameters:
            return
        self.check_parameters_against_arguments(parameters, pieces, line, scope)

    def argument_value_text_for_check(self, piece: str) -> str:
        named = split_once_outside_quotes(piece, " be ")
        return named[1] if named else piece

    def argument_type_for_check(self, pieces: list[str], index: int, scope: CheckScope) -> str | None:
        if index >= len(pieces):
            return None
        return self.infer_expression_type(self.argument_value_text_for_check(pieces[index]), scope)

    def check_collection_mutation_call(self, target: str, pieces: list[str], line: Line, scope: CheckScope) -> None:
        key = normalize(target)
        owner_text = self.argument_value_text_for_check(pieces[0]) if pieces else ""
        owner_type = self.argument_type_for_check(pieces, 0, scope)
        if not self.collection_update_type_is_explicit_for_check(owner_text, scope):
            return
        if key == "list add":
            expected = self.list_item_type_for_check(owner_type)
            actual = self.argument_type_for_check(pieces, 1, scope)
            self.check_collection_item_type("List item", expected, actual, line)
            return
        if key == "list replace at":
            expected = self.list_item_type_for_check(owner_type)
            actual = self.argument_type_for_check(pieces, 2, scope)
            self.check_collection_item_type("List item", expected, actual, line)
            return
        if key == "set add":
            expected = self.set_item_type_for_check(owner_type)
            actual = self.argument_type_for_check(pieces, 1, scope)
            self.check_collection_item_type("Set item", expected, actual, line)
            return
        if key == "map put":
            expected_key = self.map_key_type_for_check(owner_type)
            actual_key = self.argument_type_for_check(pieces, 1, scope)
            self.check_collection_item_type("Map key", expected_key, actual_key, line)
            expected_value = self.map_value_type_for_check(owner_type)
            actual_value = self.argument_type_for_check(pieces, 2, scope)
            self.check_collection_item_type("Map value", expected_value, actual_value, line)
            return
        if key == "map merge":
            expected_key = self.map_key_type_for_check(owner_type)
            expected_value = self.map_value_type_for_check(owner_type)
            incoming_type = self.argument_type_for_check(pieces, 1, scope)
            actual_key = self.map_key_type_for_check(incoming_type)
            actual_value = self.map_value_type_for_check(incoming_type)
            self.check_collection_item_type("Map key", expected_key, actual_key, line)
            self.check_collection_item_type("Map value", expected_value, actual_value, line)

    def check_collection_item_type(self, label: str, expected: str | None, actual: str | None, line: Line) -> None:
        if expected and actual and not self.type_matches(actual, expected):
            self.note(line, f"{label} must be {expected}, but it is {actual}.")

    def collection_update_type_is_explicit_for_check(self, expression: str, scope: CheckScope) -> bool:
        if not expression:
            return False
        annotated = split_once_outside_quotes(expression, " as ", last=True)
        if annotated:
            return True
        if scope.has_explicit_type(expression):
            return True
        field_split = split_once_outside_quotes(expression, " of ", last=True)
        if field_split:
            owner_type = self.infer_expression_type(field_split[1], scope)
            return bool(owner_type and self.field_type_for_check(owner_type, field_split[0]))
        return False

    def check_parameters_against_arguments(self, parameters: list[Parameter], pieces: list[str], line: Line, scope: CheckScope) -> None:
        positional_index = 0
        by_name = {normalize(parameter.name): parameter for parameter in parameters}
        variadic = next((parameter for parameter in parameters if parameter.variadic), None)
        for piece in pieces:
            named = split_once_outside_quotes(piece, " be ")
            if named:
                parameter = by_name.get(normalize(named[0]))
                value_text = named[1]
            else:
                parameter = parameters[positional_index] if positional_index < len(parameters) else variadic
                value_text = piece
                if positional_index < len(parameters) and not parameters[positional_index].variadic:
                    positional_index += 1
            if parameter and parameter.type_name:
                inferred = self.infer_expression_type(value_text, scope)
                if inferred and not self.type_matches(inferred, parameter.type_name):
                    self.note(line, f"{parameter.name} must be {parameter.type_name}, but it is {inferred}.")

    def infer_block_expression_type(self, expression: str, line: Line, scope: CheckScope) -> str | None:
        expr = expression.strip()
        if expr == "Text":
            return "String"
        if expr == "Map with":
            return self.infer_map_lines_type(line.children, scope)
        if starts(expr, "Match "):
            return self.infer_block_type(line.children, scope)
        return self.infer_expression_type(expr, scope)

    def infer_block_type(self, lines: list[Line], scope: CheckScope) -> str | None:
        if not lines:
            return "Nothing"
        return self.infer_line_type(lines[-1], scope)

    def infer_line_type(self, line: Line, scope: CheckScope) -> str | None:
        text = line.text
        if starts(text, "Make ") or starts(text, "Keep "):
            keyword = "Make " if starts(text, "Make ") else "Keep "
            split = split_once_outside_quotes(strip_prefix(text, keyword), " be ")
            if split:
                annotated = split_once_outside_quotes(split[1], " as ", last=True)
                return annotated[1] if annotated else self.infer_block_expression_type(split[1], line, scope)
            return None
        if starts(text, "Say "):
            return "Nothing"
        if starts(text, "Ignore Result "):
            return "Nothing"
        if starts(text, "Success "):
            inner = self.infer_expression_type(strip_prefix(text, "Success "), scope)
            return f"Result of {inner}" if inner else "Result"
        if starts(text, "Failure "):
            return "Result"
        return self.infer_expression_type(text, scope)

    def infer_expression_type(self, expression: str, scope: CheckScope) -> str | None:
        expr = expression.strip()
        annotated = split_once_outside_quotes(expr, " as ", last=True)
        if annotated and not starts(expr, "Use ") and not starts(expr, "New "):
            return annotated[1]
        if expr == "nothing":
            return "Nothing"
        if expr in {"true", "false"}:
            return "Bool"
        if re.fullmatch(r"-?\d+", expr):
            return "Int"
        if re.fullmatch(r"-?\d+\.\d+", expr):
            return "Float"
        if len(expr) >= 2 and expr[0] == '"' and expr[-1] == '"':
            return "String"
        for prefix in ["Need ", "Await "]:
            if starts(expr, prefix):
                return self.infer_expression_type(strip_prefix(expr, prefix), scope)
        if starts(expr, "Spawn "):
            return "Task"
        if starts(expr, "Some "):
            inner = self.infer_expression_type(strip_prefix(expr, "Some "), scope)
            return f"Maybe {inner}" if inner else "Maybe Anything"
        if starts(expr, "Success ") or starts(expr, "Failure "):
            return "Result"
        if starts(expr, "Receive from "):
            target_type = self.infer_expression_type(strip_prefix(expr, "Receive from "), scope)
            if target_type and starts(self.resolve_check_type(target_type), "Channel of "):
                return f"Maybe {strip_prefix(self.resolve_check_type(target_type), 'Channel of ')}"
            return "Maybe Anything"
        if starts(expr, "Ask"):
            return "String"
        if starts(expr, "Use "):
            return self.infer_call_type(strip_prefix(expr, "Use "), scope)
        if starts(expr, "New "):
            rest = strip_prefix(expr, "New ")
            split = split_once_outside_quotes(rest, " with ")
            return clean_name(split[0] if split else rest)
        if starts(expr, "List with "):
            item_types = [self.infer_expression_type(part, scope) for part in split_outside_quotes(strip_prefix(expr, "List with "), " and ")]
            item_type = self.common_type([item for item in item_types if item])
            return f"List of {item_type}" if item_type else "List"
        if expr == "Empty List":
            return "List"
        if starts(expr, "Set with "):
            item_types = [self.infer_expression_type(part, scope) for part in split_outside_quotes(strip_prefix(expr, "Set with "), " and ")]
            item_type = self.common_type([item for item in item_types if item])
            return f"Set of {item_type}" if item_type else "Set"
        if expr == "Empty Set":
            return "Set"
        if starts(expr, "Tuple with "):
            item_types = [self.infer_expression_type(part, scope) or "Anything" for part in split_outside_quotes(strip_prefix(expr, "Tuple with "), " and ")]
            return "Tuple of " + " and ".join(item_types)
        if starts(expr, "Map with "):
            return self.infer_inline_map_type(strip_prefix(expr, "Map with "), scope)
        if expr == "Empty Map":
            return "Map"
        if starts(expr, "Range from "):
            return "List of Int"
        if starts(expr, "Length of "):
            return "Int"
        item_match = re.match(r"Item (.+?) of (.+)$", expr)
        if item_match:
            owner_type = self.infer_expression_type(item_match.group(2), scope)
            return self.item_access_type_for_check(owner_type)
        query_match = re.match(r"Query (.+?) of (.+)$", expr)
        if query_match:
            return "Maybe String"
        if starts(expr, "not "):
            return "Bool"
        for phrase in [" or ", " and ", " is at least ", " is at most ", " is greater than ", " is less than ", " is not ", " is in ", " is "]:
            if split_once_outside_quotes(expr, phrase):
                return "Bool"
        for phrase in [" plus ", " minus ", " times ", " over ", " remainder "]:
            split = split_once_outside_quotes(expr, phrase, last=True)
            if split:
                left = self.infer_expression_type(split[0], scope)
                right = self.infer_expression_type(split[1], scope)
                if phrase == " plus " and left == "String" and right == "String":
                    return "String"
                if left == "Float" or right == "Float" or phrase == " over ":
                    return "Float"
                if left == "Int" and right == "Int":
                    return "Int"
                return None
        field_split = split_once_outside_quotes(expr, " of ", last=True)
        if field_split:
            owner_type = self.infer_expression_type(field_split[1], scope)
            if owner_type:
                return self.field_type_for_check(owner_type, field_split[0]) or self.method_return_type_for_check(owner_type, field_split[0])
        return scope.get_type(expr)

    def infer_call_type(self, text: str, scope: CheckScope) -> str | None:
        split = split_once_outside_quotes(text, " with ")
        target = split[0] if split else text
        args_text = split[1] if split else ""
        method_split = split_once_outside_quotes(target, " of ", last=True)
        if method_split:
            method_name, owner_expression = method_split
            if starts(method_name, "Parent "):
                parent = self.type_parents.get(normalize(scope.current_type or ""))
                return self.method_return_type_for_check(parent, strip_prefix(method_name, "Parent ")) if parent else None
            owner_type = self.infer_expression_type(owner_expression, scope)
            return self.method_return_type_for_check(owner_type, method_name)
        key = normalize(target)
        if key in {"string lower", "string upper", "string trim", "string join", "time format", "text"}:
            return "String"
        if key in {"string contains", "string starts with", "string ends with", "file exists", "regex match", "map has"}:
            return "Bool"
        if key in {"math round", "int parse"}:
            return "Int" if key == "math round" else "Result"
        if key in {"float parse", "math sqrt"}:
            return "Float" if key == "math sqrt" else "Result"
        if key in {"json parse", "json serialize", "file read", "file write", "file delete", "http get", "http post"}:
            return "Result"
        if key in {"async all", "async race"}:
            return "Task"
        if key in {"time now", "os args", "file walk"}:
            return "List" if key in {"os args", "file walk"} else "Anything"
        if key == "map get":
            pieces = split_arguments(args_text) if args_text else []
            value_type = self.map_value_type_for_check(self.infer_expression_type(pieces[0], scope) if pieces else None)
            default_type = None
            has_default = False
            if len(pieces) > 2:
                has_default = True
                default_type = self.infer_expression_type(pieces[2], scope)
            for piece in pieces:
                named = split_once_outside_quotes(piece, " be ")
                if named and normalize(named[0]) == "otherwise":
                    has_default = True
                    default_type = self.infer_expression_type(named[1], scope)
            if has_default:
                return self.common_type([value_type, default_type]) or value_type or default_type
            return self.make_maybe_type(value_type or "Anything")
        if key in {"map put", "map remove", "map merge"}:
            return "Map"
        if key == "map keys":
            pieces = split_arguments(args_text) if args_text else []
            key_type = self.map_key_type_for_check(self.infer_expression_type(pieces[0], scope) if pieces else None)
            return f"List of {key_type}" if key_type else "List"
        if key == "map values":
            pieces = split_arguments(args_text) if args_text else []
            value_type = self.map_value_type_for_check(self.infer_expression_type(pieces[0], scope) if pieces else None)
            return f"List of {value_type}" if value_type else "List"
        if key == "map entries":
            return "List"
        return None

    def map_key_type_for_check(self, map_type: str | None) -> str | None:
        if not map_type:
            return None
        resolved = self.resolve_check_type(map_type)
        if starts(resolved, "Map of "):
            split = split_once_outside_quotes(strip_prefix(resolved, "Map of "), " to ")
            if split:
                return split[0]
        return None

    def map_value_type_for_check(self, map_type: str | None) -> str | None:
        if not map_type:
            return None
        resolved = self.resolve_check_type(map_type)
        if starts(resolved, "Map of "):
            split = split_once_outside_quotes(strip_prefix(resolved, "Map of "), " to ")
            if split:
                return split[1]
        return None

    def channel_item_type_for_check(self, channel_type: str | None) -> str | None:
        if not channel_type:
            return None
        resolved = self.resolve_check_type(channel_type)
        if starts(resolved, "Channel of "):
            return strip_prefix(resolved, "Channel of ")
        return None

    def infer_inline_map_type(self, text: str, scope: CheckScope) -> str | None:
        key_types: list[str] = []
        value_types: list[str] = []
        if text:
            for piece in split_outside_quotes(text, " and "):
                split = split_once_outside_quotes(piece, " meaning ")
                if split:
                    key = self.infer_expression_type(split[0], scope)
                    value = self.infer_expression_type(split[1], scope)
                    if key:
                        key_types.append(key)
                    if value:
                        value_types.append(value)
        key_type = self.common_type(key_types)
        value_type = self.common_type(value_types)
        return f"Map of {key_type} to {value_type}" if key_type and value_type else "Map"

    def infer_map_lines_type(self, lines: list[Line], scope: CheckScope) -> str | None:
        key_types: list[str] = []
        value_types: list[str] = []
        for line in lines:
            split = split_once_outside_quotes(line.text, " meaning ")
            if split:
                key = self.infer_expression_type(split[0], scope)
                value = self.infer_expression_type(split[1], scope)
                if key:
                    key_types.append(key)
                if value:
                    value_types.append(value)
        key_type = self.common_type(key_types)
        value_type = self.common_type(value_types)
        return f"Map of {key_type} to {value_type}" if key_type and value_type else "Map"

    def common_type(self, types: list[str]) -> str | None:
        clean = [self.resolve_check_type(type_name) for type_name in types if type_name]
        if not clean:
            return None
        absence = any(type_name == "Nothing" or starts(type_name, "Maybe ") for type_name in clean)
        if absence:
            present = [
                strip_prefix(type_name, "Maybe ") if starts(type_name, "Maybe ") else type_name
                for type_name in clean
                if type_name != "Nothing"
            ]
            if not present:
                return "Nothing"
            base = self.common_type(present) or "Anything"
            return self.make_maybe_type(base)
        first = clean[0]
        if all(type_name == first for type_name in clean):
            return first
        if all(type_name in {"Int", "Float"} for type_name in clean):
            return "Float"
        return "Anything"

    def resolve_check_type(self, type_name: str) -> str:
        current = type_name.strip()
        seen: set[str] = set()
        while normalize(current) in self.type_aliases and normalize(current) not in seen:
            seen.add(normalize(current))
            current = self.type_aliases[normalize(current)]
        return current

    def type_matches(self, actual: str, expected: str) -> bool:
        actual = self.resolve_check_type(actual)
        expected = self.resolve_check_type(expected)
        if expected in {"Anything", "Any"} or actual in {"Anything", "Any"}:
            return True
        union = split_once_outside_quotes(expected, " or ")
        if union:
            return self.type_matches(actual, union[0]) or self.type_matches(actual, union[1])
        if starts(expected, "Maybe "):
            if starts(actual, "Maybe "):
                return self.type_matches(strip_prefix(actual, "Maybe "), strip_prefix(expected, "Maybe "))
            return actual == "Nothing" or self.type_matches(actual, strip_prefix(expected, "Maybe "))
        if actual == "Nothing":
            return False
        if expected == "List":
            return actual == "List" or starts(actual, "List of ")
        if expected == "Set":
            return actual == "Set" or starts(actual, "Set of ")
        if expected == "Map":
            return actual == "Map" or starts(actual, "Map of ")
        if expected == "Tuple":
            return actual == "Tuple" or starts(actual, "Tuple of ")
        if starts(expected, "List of "):
            return actual == "List" or (starts(actual, "List of ") and self.type_matches(strip_prefix(actual, "List of "), strip_prefix(expected, "List of ")))
        if starts(expected, "Set of "):
            return actual == "Set" or (starts(actual, "Set of ") and self.type_matches(strip_prefix(actual, "Set of "), strip_prefix(expected, "Set of ")))
        if starts(expected, "Map of "):
            if actual == "Map":
                return True
            expected_parts = split_once_outside_quotes(strip_prefix(expected, "Map of "), " to ")
            actual_parts = split_once_outside_quotes(strip_prefix(actual, "Map of "), " to ") if starts(actual, "Map of ") else None
            return bool(expected_parts and actual_parts and self.type_matches(actual_parts[0], expected_parts[0]) and self.type_matches(actual_parts[1], expected_parts[1]))
        if starts(expected, "Tuple of "):
            if not starts(actual, "Tuple of "):
                return False
            expected_items = split_outside_quotes(strip_prefix(expected, "Tuple of "), " and ")
            actual_items = split_outside_quotes(strip_prefix(actual, "Tuple of "), " and ")
            return len(expected_items) == len(actual_items) and all(self.type_matches(got, want) for got, want in zip(actual_items, expected_items))
        if expected == "Float" and actual == "Int":
            return True
        current = normalize(actual)
        wanted = normalize(expected)
        while current:
            if current == wanted:
                return True
            parent = self.type_parents.get(current)
            current = normalize(parent) if parent else ""
        return actual == expected


def check_source(source: str, label: str = "document", base_dir: Path | None = None) -> list[dict[str, Any]]:
    diagnostics = lint_source(source, label)
    try:
        program = parse_program(source)
    except PlainError:
        return diagnostics
    diagnostics.extend(SemanticChecker(label, base_dir=base_dir).check(program))
    return diagnostics


def is_expected_error_source(source: str) -> bool:
    return any(starts(line.strip(), "Note Expected Error") for line in source.splitlines())


def check_path(path: Path) -> int:
    if not path.exists():
        print(f"Plain English error: Could not check {path}. The path does not exist.", file=sys.stderr)
        return 1
    files = language_files(path)
    directory_mode = path.is_dir()
    failures = 0
    for file in files:
        try:
            source = file.read_text(encoding="utf-8")
            if directory_mode and is_expected_error_source(source):
                print(f"Skipped expected error example {file}.")
                continue
            diagnostics = check_source(source, str(file), base_dir=file.parent)
        except OSError as error:
            diagnostics = [make_diagnostic(1, 1, f"Could not read {file}: {error}")]
        if diagnostics:
            failures += 1
            for diagnostic in diagnostics:
                line = diagnostic["range"]["start"]["line"] + 1
                print(f"Plain English error: {file} line {line}: {diagnostic['message']}", file=sys.stderr)
        else:
            print(f"{file} checks clean.")
    if failures:
        print(f"{failures} file(s) did not check cleanly.", file=sys.stderr)
        return 1
    print(f"All {len(files)} file(s) check clean.")
    return 0


def make_diagnostic(line: int, column: int, message: str) -> dict[str, Any]:
    return {
        "range": {
            "start": {"line": max(0, line - 1), "character": max(0, column - 1)},
            "end": {"line": max(0, line - 1), "character": max(1, column)},
        },
        "severity": 1,
        "source": "twohundredseventyone",
        "message": message,
    }


def format_source(source: str) -> str:
    formatted = []
    for line in source.splitlines():
        if not line.strip():
            formatted.append("")
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = " ".join(line.strip().split())
        formatted.append(" " * indent + body)
    return "\n".join(formatted) + "\n"


def docs_for(path: Path) -> int:
    files = sorted(path.rglob("*.271")) if path.is_dir() else [path]
    lines = ["# twohundredseventyone generated docs", ""]
    for file in files:
        try:
            program = parse_program(file.read_text(encoding="utf-8"))
        except PlainError as error:
            print(f"Plain English error: {error}", file=sys.stderr)
            return 1
        lines.append(f"## {file}")
        lines.append("")
        collect_docs(program, lines)
        lines.append("")
    output = Path("271-docs.md")
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {output}.")
    return 0


def collect_docs(program: list[Line], lines: list[str]) -> None:
    for line in program:
        text = line.text
        for prefix, label in [
            ("Record ", "Record"),
            ("Object ", "Object"),
            ("Problem ", "Problem"),
            ("Contract ", "Contract"),
            ("Type ", "Type"),
            ("Private Teach ", "Private Teaching"),
            ("Private Async Teach ", "Private Async Teaching"),
            ("Teach ", "Teaching"),
            ("Async Teach ", "Async Teaching"),
            ("Test Teach ", "Test"),
            ("Use Parent ", "Parent Call"),
        ]:
            if starts(text, prefix):
                lines.append(f"- {label}: `{strip_prefix(text, prefix)}`")
                break
        collect_docs(line.children, lines)


def add_package(name: str, remote_url: str | None = None) -> int:
    package_path = Path("271.package")
    lock_path = Path("271.lock")
    packages_path = Path("packages") / name
    source_label = "local-registry"
    if remote_url:
        installed = install_remote_package(name, remote_url, packages_path)
        if not installed.ok:
            print(f"Plain English error: {installed.value}", file=sys.stderr)
            return 1
        version = installed.value
        source_label = remote_url.rstrip("/")
    else:
        registry_path = Path("registry") / name
        if not registry_path.exists():
            print(f"Plain English error: The package {name} is not in the local registry.", file=sys.stderr)
            return 1
        package_manifest_path = registry_path / "271.package"
        version = "local"
        if package_manifest_path.exists():
            try:
                version = json.loads(package_manifest_path.read_text(encoding="utf-8")).get("version", "local")
            except json.JSONDecodeError:
                print(f"Plain English error: {package_manifest_path} is not valid JSON.", file=sys.stderr)
                return 1
        if packages_path.exists():
            shutil.rmtree(packages_path)
        shutil.copytree(registry_path, packages_path)
    if package_path.exists():
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("Plain English error: 271.package is not valid JSON.", file=sys.stderr)
            return 1
    else:
        package = {"name": "local-project", "dependencies": {}}
    package.setdefault("dependencies", {})[name] = version
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    lock = {
        "dependencies": {
            dep: {"version": dep_version, "source": source_label if dep == name else "local-registry"}
            for dep, dep_version in package["dependencies"].items()
        }
    }
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"Installed {name} from {source_label}.")
    return 0


def install_remote_package(name: str, remote_url: str, target: Path) -> Result:
    base = remote_url.rstrip("/")
    try:
        meta_request = url_request.Request(f"{base}/packages/{name}")
        with url_request.urlopen(meta_request, timeout=10) as response:
            metadata = json.loads(response.read().decode("utf-8"))
        zip_request = url_request.Request(f"{base}/packages/{name}.zip")
        with url_request.urlopen(zip_request, timeout=10) as response:
            archive = response.read()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return Result.failure(f"Could not install {name} from {remote_url}: {error}")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(BytesIO(archive)) as package_zip:
            for member in package_zip.infolist():
                destination = (target / member.filename).resolve()
                if not str(destination).startswith(str(target.resolve())):
                    return Result.failure(f"The package {name} contains an unsafe path.")
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(package_zip.read(member))
    except zipfile.BadZipFile:
        return Result.failure(f"The package {name} did not download as a valid zip file.")
    return Result.success(metadata.get("version", "remote"))


def serve_registry(port: int = 2711, registry_root: Path | None = None) -> int:
    root = (registry_root or Path("registry")).resolve()
    if not root.exists():
        print(f"Plain English error: {root} does not exist.", file=sys.stderr)
        return 1

    class RegistryHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                status, content, content_type = self.route()
            except Exception as error:
                status, content, content_type = 500, f"Plain English error: {error}".encode("utf-8"), "text/plain"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def route(self) -> tuple[int, bytes, str]:
            path = urlparse(self.path).path.strip("/")
            if path == "packages":
                packages = [read_package_metadata(package) for package in sorted(root.iterdir()) if package.is_dir()]
                return 200, json.dumps({"packages": packages}).encode("utf-8"), "application/json"
            match = re.fullmatch(r"packages/([^/]+)\.zip", path)
            if match:
                package = root / match.group(1)
                if not package.exists():
                    return 404, b"Package not found", "text/plain"
                return 200, zip_package(package), "application/zip"
            match = re.fullmatch(r"packages/([^/]+)", path)
            if match:
                package = root / match.group(1)
                if not package.exists():
                    return 404, b"Package not found", "text/plain"
                return 200, json.dumps(read_package_metadata(package)).encode("utf-8"), "application/json"
            return 404, b"Not found", "text/plain"

    server = ThreadingHTTPServer(("127.0.0.1", port), RegistryHandler)
    print(f"Serving twohundredseventyone packages on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Registry server stopped.")
    return 0


def read_package_metadata(package: Path) -> dict[str, Any]:
    manifest = package / "271.package"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data.setdefault("name", package.name)
            return data
        except json.JSONDecodeError:
            return {"name": package.name, "version": "broken", "error": "271.package is not valid JSON"}
    return {"name": package.name, "version": "local"}


def zip_package(package: Path) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package_zip:
        for file in sorted(package.rglob("*")):
            if file.is_file():
                package_zip.write(file, file.relative_to(package).as_posix())
    return buffer.getvalue()


def new_project(path: Path) -> int:
    try:
        if path.exists() and any(path.iterdir()):
            print(f"Plain English error: {path} already has files in it.", file=sys.stderr)
            return 1
        path.mkdir(parents=True, exist_ok=True)
        tests_dir = path / "tests"
        tests_dir.mkdir(exist_ok=True)
        name = project_name(path)
        (path / "app.271").write_text(
            f'Keep App Name be "{name}"\n\n'
            "Teach Main\n"
            '  Say "Hello from {App Name}"\n'
            '  Say "jew is {jew}"\n',
            encoding="utf-8",
        )
        (tests_dir / "app.271").write_text(
            "Expect jew is 271\n"
            'Expect "hello" is "hello"\n',
            encoding="utf-8",
        )
        (path / "271.package").write_text(json.dumps({
            "name": name,
            "version": "0.1.0",
            "dependencies": {},
        }, indent=2) + "\n", encoding="utf-8")
        (path / "README.md").write_text(
            f"# {name}\n\n"
            "A twohundredseventyone project.\n\n"
            "```powershell\n"
            ".\\271.cmd doctor\n"
            ".\\271.cmd check .\n"
            ".\\271.cmd run .\\app.271\n"
            ".\\271.cmd test .\\tests\n"
            "```\n",
            encoding="utf-8",
        )
        shutil.copyfile(Path(__file__), path / "271.py")
        (path / "271.cmd").write_text(f'@echo off\n"{sys.executable}" "%~dp0271.py" %*\n', encoding="utf-8")
        (path / "271.ps1").write_text(f'& "{sys.executable}" "$PSScriptRoot\\271.py" @args\n', encoding="utf-8")
        print(f"Created twohundredseventyone project in {path}.")
        print(f"Run it with: cd {path} ; .\\271.cmd run .\\app.271")
        return 0
    except OSError as error:
        print(f"Plain English error: Could not create project: {error}", file=sys.stderr)
        return 1


def project_name(path: Path) -> str:
    text = re.sub(r"[^A-Za-z0-9 -]+", "", path.name).strip().lower()
    text = re.sub(r"\s+", "-", text)
    return text or "twohundredseventyone-app"


def doctor(path: Path | None = None) -> int:
    root = (path or Path.cwd()).resolve()
    checks: list[tuple[bool, str]] = []

    def add_check(ok: bool, message: str) -> None:
        checks.append((ok, message))

    runner_path = Path(__file__).resolve()
    add_check(runner_path.exists(), f"Runner exists at {runner_path}")
    add_check(sys.version_info >= (3, 10), f"Python is {sys.version.split()[0]}")
    add_check(Path(sys.executable).exists(), f"Python executable exists at {sys.executable}")

    launcher = root / "271.cmd"
    add_check(launcher.exists(), f"Windows launcher exists at {launcher}")

    manifest = root / "271.package"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            add_check(isinstance(data.get("name"), str) and bool(data["name"].strip()), "271.package has a project name")
            add_check(isinstance(data.get("dependencies", {}), dict), "271.package dependencies are readable")
        except json.JSONDecodeError as error:
            add_check(False, f"271.package is not valid JSON: {error.msg}")
    else:
        add_check(False, f"271.package exists at {manifest}")

    files = language_files(root)
    add_check(bool(files), f"Found {len(files)} .271 file(s)")
    readable = True
    for file in files:
        try:
            parse_program(file.read_text(encoding="utf-8"))
        except (OSError, PlainError):
            readable = False
            break
    add_check(readable, "All .271 files parse as readable code")
    semantic_clean = True
    for file in files:
        try:
            source = file.read_text(encoding="utf-8")
            if is_expected_error_source(source):
                continue
            if check_source(source, str(file), base_dir=file.parent):
                semantic_clean = False
                break
        except OSError:
            semantic_clean = False
            break
    add_check(semantic_clean, "All .271 files pass semantic checks")

    tests = language_files(root / "tests") if (root / "tests").exists() else []
    add_check(bool(tests), f"Found {len(tests)} test file(s)")

    failures = 0
    for ok, message in checks:
        if ok:
            print(f"Good: {message}.")
        else:
            failures += 1
            print(f"Plain English error: {message}.", file=sys.stderr)
    if failures:
        print(f"{failures} doctor check(s) need attention.", file=sys.stderr)
        return 1
    print("Doctor found the toolchain ready.")
    return 0


def build_project(path: Path) -> int:
    build_dir = Path("build")
    build_dir.mkdir(exist_ok=True)
    files = language_files(path)
    manifest = {
        "runner": VERSION,
        "files": [str(file) for file in files],
    }
    (build_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(Path(__file__), build_dir / "271.py")
    launcher = build_dir / "271.cmd"
    launcher.write_text(f'@echo off\n"{sys.executable}" "%~dp0271.py" %*\n', encoding="utf-8")
    for file in files:
        relative = file.relative_to(path) if path.is_dir() else Path(file.name)
        target = build_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.read_text(encoding="utf-8"), encoding="utf-8")
    for folder_name in ["packages", "registry"]:
        source_folder = Path(folder_name)
        target_folder = build_dir / folder_name
        if source_folder.exists():
            if target_folder.exists():
                shutil.rmtree(target_folder)
            shutil.copytree(source_folder, target_folder)
    for metadata in ["271.package", "271.lock"]:
        source_file = Path(metadata)
        if source_file.exists():
            shutil.copyfile(source_file, build_dir / metadata)
    print(f"Built {len(files)} file(s) into {build_dir}.")
    return 0


def compile_project(path: Path) -> int:
    cache_dir = Path(".271-cache")
    cache_dir.mkdir(exist_ok=True)
    files = language_files(path)
    failures = 0
    compiled = 0
    directory_mode = path.is_dir()
    for file in files:
        if directory_mode:
            try:
                if is_expected_error_source(file.read_text(encoding="utf-8")):
                    print(f"Skipped expected error example {file}.")
                    continue
            except OSError as error:
                print(f"Plain English error: Could not read {file}: {error}", file=sys.stderr)
                failures += 1
                continue
        if compile_file(file, cache_dir, path if path.is_dir() else file.parent) != 0:
            failures += 1
        else:
            compiled += 1
    if failures:
        print(f"{failures} file(s) did not compile.", file=sys.stderr)
        return 1
    print(f"Compiled {compiled} file(s) into {cache_dir}.")
    return 0


def compile_file(file: Path, cache_dir: Path, root: Path) -> int:
    try:
        relative = file.relative_to(root) if root.is_dir() else Path(file.name)
        target = cache_dir / relative.with_suffix(".271c")
        target.parent.mkdir(parents=True, exist_ok=True)
        artifact = make_compile_artifact(file)
        target.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        print(f"Compiled {file} to {target}.")
        return 0
    except PlainError as error:
        print(format_plain_error(error), file=sys.stderr)
        return 1


def make_compile_artifact(file: Path) -> dict[str, Any]:
    source = file.read_text(encoding="utf-8")
    program = parse_program(source, source_label=str(file))
    diagnostics = check_source(source, str(file), base_dir=file.parent)
    if diagnostics:
        messages = "; ".join(diagnostic["message"] for diagnostic in diagnostics)
        raise PlainError(f"{file}: {messages}")
    declarations: list[str] = []
    collect_docs(program, declarations)
    program_data = line_to_data(program)
    program_hash = hashlib.sha256(json.dumps(program_data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    constants = find_compile_time_constants(program)
    return {
        "language": "twohundredseventyone",
        "runner": VERSION,
        "source": str(file),
        "hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "program_hash": program_hash,
        "line_count": len(source.splitlines()),
        "declarations": declarations,
        "compile_time_constants": constants,
        "program": program_data,
    }


def line_to_data(lines: list[Line]) -> list[dict[str, Any]]:
    return [
        {
            "text": line.text,
            "number": line.number,
            "indent": line.indent,
            "source": line.source,
            "children": line_to_data(line.children),
        }
        for line in lines
    ]


def line_from_data(items: list[dict[str, Any]]) -> list[Line]:
    return [
        Line(
            text=str(item["text"]),
            number=int(item.get("number", 0)),
            indent=int(item.get("indent", 0)),
            source=str(item.get("source", "compiled program")),
            children=line_from_data(item.get("children", [])),
        )
        for item in items
    ]


def find_compile_time_constants(program: list[Line]) -> dict[str, Any]:
    constants: dict[str, Any] = {}
    runner = Runner()
    for line in program:
        if starts(line.text, "Keep ") and not line.children:
            rest = strip_prefix(line.text, "Keep ")
            split = split_once_outside_quotes(rest, " be ")
            if not split:
                continue
            name, expression = split
            try:
                constants[clean_name(name)] = runner.to_jsonable(runner.eval_expression(expression, runner.global_env))
            except Exception:
                continue
        constants.update(find_compile_time_constants(line.children))
    return constants


def run_compiled(path: Path, extra_args: list[str]) -> int:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if artifact.get("language") != "twohundredseventyone":
            print("Plain English error: This is not a twohundredseventyone compiled file.", file=sys.stderr)
            return 1
        program_data = artifact.get("program")
        if not isinstance(program_data, list):
            print("Plain English error: This compiled file does not contain a compiled program tree.", file=sys.stderr)
            return 1
        program_hash = hashlib.sha256(json.dumps(program_data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if program_hash != artifact.get("program_hash"):
            print("Plain English error: This compiled program tree has been changed since it was written.", file=sys.stderr)
            return 1
        program = line_from_data(program_data)
        runner = Runner(argv=extra_args, base_dir=path.parent)
        runner.execute_program(program)
        return 0
    except (OSError, json.JSONDecodeError) as error:
        print(f"Plain English error: Could not read compiled file: {error}", file=sys.stderr)
        return 1
    except PlainError as error:
        print(format_plain_error(error), file=sys.stderr)
        return 1


def pack_app(path: Path) -> int:
    try:
        if path.suffix.lower() == ".271c":
            artifact = json.loads(path.read_text(encoding="utf-8"))
            stem = path.stem
        elif path.suffix.lower() == ".271":
            artifact = make_compile_artifact(path)
            stem = path.stem
        else:
            print("Plain English error: pack needs a .271 or .271c file.", file=sys.stderr)
            return 1
        if artifact.get("language") != "twohundredseventyone" or not isinstance(artifact.get("program"), list):
            print("Plain English error: pack needs a valid twohundredseventyone program.", file=sys.stderr)
            return 1
        dist = Path("dist")
        dist.mkdir(exist_ok=True)
        target = dist / f"{stem}.pyz"
        artifact_text = json.dumps(artifact, separators=(",", ":"))
        encoded_artifact = base64.b64encode(artifact_text.encode("utf-8")).decode("ascii")
        runner_text = Path(__file__).read_text(encoding="utf-8")
        main_text = make_pack_main(encoded_artifact)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("__main__.py", main_text)
            package.writestr("runner271.py", runner_text)
            package.writestr("271.package.json", json.dumps({
                "language": "twohundredseventyone",
                "runner": VERSION,
                "source": artifact.get("source"),
                "program_hash": artifact.get("program_hash"),
            }, indent=2))
        print(f"Packed {path} into {target}.")
        return 0
    except (OSError, json.JSONDecodeError) as error:
        print(f"Plain English error: Could not pack {path}: {error}", file=sys.stderr)
        return 1
    except PlainError as error:
        print(f"Plain English error: {error}", file=sys.stderr)
        return 1


def make_pack_main(encoded_artifact: str) -> str:
    return f'''import base64
import hashlib
import json
import sys
from pathlib import Path

import runner271

ARTIFACT = {encoded_artifact!r}


def main():
    artifact = json.loads(base64.b64decode(ARTIFACT).decode("utf-8"))
    program = artifact.get("program")
    program_hash = hashlib.sha256(json.dumps(program, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if program_hash != artifact.get("program_hash"):
        print("Plain English error: This packaged program has been changed since it was packed.", file=sys.stderr)
        return 1
    runner = runner271.Runner(argv=sys.argv[1:], base_dir=Path.cwd())
    try:
        runner.execute_program(runner271.line_from_data(program))
        return 0
    except runner271.PlainError as error:
        print(runner271.format_plain_error(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def emit_python(path: Path) -> int:
    try:
        if path.suffix.lower() != ".271":
            print("Plain English error: emit-python needs a .271 file.", file=sys.stderr)
            return 1
        source = path.read_text(encoding="utf-8")
        program = parse_program(source)
        emitter = PythonEmitter()
        python_source = emitter.emit(program)
        output_dir = Path("emitted")
        output_dir.mkdir(exist_ok=True)
        target = output_dir / f"{path.stem}.py"
        target.write_text(python_source, encoding="utf-8")
        print(f"Emitted {path} to {target}.")
        return 0
    except PlainError as error:
        print(f"Plain English error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Plain English error: Could not emit Python: {error}", file=sys.stderr)
        return 1


class PythonEmitter:
    def __init__(self):
        self.temp_index = 0

    def emit(self, program: list[Line]) -> str:
        lines = [
            "# Generated by twohundredseventyone.",
            "class _Result:",
            "  def __init__(self, ok, value):",
            "    self.ok = ok",
            "    self.value = value",
            "  def __eq__(self, other):",
            "    return isinstance(other, _Result) and self.ok == other.ok and self.value == other.value",
            "  def __repr__(self):",
            "    label = 'Success' if self.ok else 'Failure'",
            "    return f'{label} {self.value!r}'",
            "",
            "def _need(value):",
            "  if isinstance(value, _Result):",
            "    if value.ok:",
            "      return value.value",
            "    raise RuntimeError(f'Plain English error: {value.value}')",
            "  return value",
            "",
            "jew = 271",
            "",
            "def _say(value):",
            "  if isinstance(value, str) and value.strip().lower() == 'jew':",
            "    value = jew",
            "  print(value)",
            "",
            "def _range_inclusive(start, end, step=1):",
            "  if step == 0:",
            "    raise RuntimeError('Plain English error: A range step cannot be zero.')",
            "  stop = end + (1 if step > 0 else -1)",
            "  return range(start, stop, step)",
            "",
        ]
        lines.extend(self.emit_block(program, 0))
        if any(starts(line.text, "Teach Main") for line in program):
            lines.extend(["", "if __name__ == \"__main__\":", "  main()"])
        return "\n".join(lines).rstrip() + "\n"

    def emit_block(self, block: list[Line], indent: int) -> list[str]:
        output: list[str] = []
        index = 0
        while index < len(block):
            line = block[index]
            text = line.text
            if starts(text, "Otherwise") or starts(text, "Catch ") or text == "Finally" or starts(text, "When "):
                index += 1
                continue
            if starts(text, "If "):
                emitted, index = self.emit_if_chain(block, index, indent)
                output.extend(emitted)
                continue
            if starts(text, "Match "):
                output.extend(self.emit_match(line, indent))
                index += 1
                continue
            if starts(text, "Repeat "):
                output.extend(self.emit_repeat(line, indent))
                index += 1
                continue
            if text == "Try":
                emitted, index = self.emit_try_chain(block, index, indent)
                output.extend(emitted)
                continue
            output.extend(self.emit_line(line, indent))
            index += 1
        return output or [self.pad(indent) + "pass"]

    def emit_line(self, line: Line, indent: int) -> list[str]:
        text = line.text
        pad = self.pad(indent)
        if starts(text, "Make ") or starts(text, "Keep "):
            keyword = "Make " if starts(text, "Make ") else "Keep "
            rest = strip_prefix(text, keyword)
            split = split_once_outside_quotes(rest, " be ")
            if not split:
                raise PlainError(f"Line {line.number} needs the word be.")
            name, expression = split
            annotated = split_once_outside_quotes(expression, " as ", last=True)
            if annotated:
                expression = annotated[0]
            names = [python_name(part) for part in split_outside_quotes(name, " and ")]
            target = ", ".join(names)
            return [pad + f"{target} = {self.expr(expression)}"]
        if starts(text, "Change "):
            rest = strip_prefix(text, "Change ")
            split = split_once_outside_quotes(rest, " to ")
            if not split:
                raise PlainError(f"Line {line.number} needs the word to.")
            return [pad + f"{python_name(split[0])} = {self.expr(split[1])}"]
        if text == "Stop":
            return [pad + "break"]
        if text == "Skip":
            return [pad + "continue"]
        if starts(text, "Say "):
            return [pad + f"_say({self.expr(strip_prefix(text, 'Say '))})"]
        if starts(text, "Teach "):
            return self.emit_teach(line, indent)
        if starts(text, "Expect "):
            expression = strip_prefix(text, "Expect ")
            split = split_once_outside_quotes(expression, " is ")
            if not split:
                raise PlainError(f"Line {line.number} needs the word is in the expectation.")
            return [pad + f"assert {self.expr(split[0])} == {self.expr(split[1])}"]
        if starts(text, "Ignore Result "):
            return [pad + f"_ = {self.expr(strip_prefix(text, 'Ignore Result '))}"]
        if starts(text, "Bring ") or starts(text, "Note ") or starts(text, "Type ") or starts(text, "Contract ") or starts(text, "Problem ") or starts(text, "Record ") or starts(text, "Object "):
            return []
        return [pad + self.expr(text)]

    def emit_teach(self, line: Line, indent: int) -> list[str]:
        rest = strip_prefix(line.text, "Teach ")
        returns = split_once_outside_quotes(rest, " returns ")
        if returns:
            rest = returns[0]
        using = split_once_outside_quotes(rest, " using ")
        if using:
            name, params_text = using
            params = [self.parameter_source(parameter) for parameter in parse_parameters(params_text)]
        else:
            name = rest
            params = []
        output = [self.pad(indent) + f"def {python_name(name)}({', '.join(params)}):"]
        body = self.emit_block(line.children, indent + 1)
        if body:
            last = body[-1].strip()
            if not last.startswith(("return ", "print(", "assert ", "if ", "for ", "while ", "try:", "break", "continue", "pass")) and " = " not in last:
                body[-1] = self.pad(indent + 1) + "return " + last
        output.extend(body)
        return output

    def parameter_source(self, parameter: Parameter) -> str:
        name = python_name(parameter.name)
        if parameter.variadic:
            return "*" + name
        if parameter.default is not None:
            return f"{name}={self.expr(parameter.default)}"
        return name

    def emit_if_chain(self, block: list[Line], start_index: int, indent: int) -> tuple[list[str], int]:
        output: list[str] = []
        first = block[start_index]
        output.append(self.pad(indent) + f"if {self.expr(strip_prefix(first.text, 'If '))}:")
        output.extend(self.emit_block(first.children, indent + 1))
        index = start_index + 1
        while index < len(block):
            text = block[index].text
            if starts(text, "Otherwise if "):
                output.append(self.pad(indent) + f"elif {self.expr(strip_prefix(text, 'Otherwise if '))}:")
                output.extend(self.emit_block(block[index].children, indent + 1))
                index += 1
            elif text == "Otherwise":
                output.append(self.pad(indent) + "else:")
                output.extend(self.emit_block(block[index].children, indent + 1))
                index += 1
                break
            else:
                break
        return output, index

    def emit_repeat(self, line: Line, indent: int) -> list[str]:
        text = line.text
        if starts(text, "Repeat for "):
            header = strip_prefix(text, "Repeat for ")
            split = split_once_outside_quotes(header, " in ")
            if not split:
                raise PlainError(f"Line {line.number} needs the word in.")
            names = [python_name(name) for name in split_outside_quotes(split[0], " and ")]
            output = [self.pad(indent) + f"for {', '.join(names)} in {self.expr(split[1])}:"]
            output.extend(self.emit_block(line.children, indent + 1))
            return output
        if starts(text, "Repeat while "):
            output = [self.pad(indent) + f"while {self.expr(strip_prefix(text, 'Repeat while '))}:"]
            output.extend(self.emit_block(line.children, indent + 1))
            return output
        if text == "Repeat forever":
            output = [self.pad(indent) + "while True:"]
            output.extend(self.emit_block(line.children, indent + 1))
            return output
        raise PlainError(f"Python emit does not yet support line {line.number}: {text}")

    def emit_match(self, line: Line, indent: int) -> list[str]:
        value_name = self.temp_name("match value")
        output = [self.pad(indent) + f"{value_name} = {self.expr(strip_prefix(line.text, 'Match '))}"]
        emitted_any = False
        for child in line.children:
            if not starts(child.text, "When "):
                continue
            condition, bindings = self.match_condition(strip_prefix(child.text, "When "), value_name)
            keyword = "if" if not emitted_any else "elif"
            output.append(self.pad(indent) + f"{keyword} {condition}:")
            for name, source in bindings:
                output.append(self.pad(indent + 1) + f"{python_name(name)} = {source}")
            output.extend(self.emit_block(child.children, indent + 1))
            emitted_any = True
        if not emitted_any:
            raise PlainError(f"Line {line.number} needs at least one When branch.")
        output.append(self.pad(indent) + "else:")
        output.append(self.pad(indent + 1) + "raise RuntimeError('Plain English error: This match did not handle the value it received.')")
        return output

    def match_condition(self, pattern: str, value_name: str) -> tuple[str, list[tuple[str, str]]]:
        pattern = pattern.strip()
        if pattern == "anything":
            return "True", []
        if pattern == "nothing":
            return f"{value_name} is None", []
        if starts(pattern, "Some "):
            name = strip_prefix(pattern, "Some ")
            return f"{value_name} is not None", [(name, value_name)]
        if starts(pattern, "Success "):
            name = strip_prefix(pattern, "Success ")
            return f"isinstance({value_name}, _Result) and {value_name}.ok", [(name, f"{value_name}.value")]
        if starts(pattern, "Failure "):
            name = strip_prefix(pattern, "Failure ")
            return f"isinstance({value_name}, _Result) and not {value_name}.ok", [(name, f"{value_name}.value")]
        named = split_once_outside_quotes(pattern, " named ")
        if named:
            type_name, bind_name = named
            return self.type_condition(value_name, type_name), [(bind_name, value_name)]
        if pattern in {"Int", "Float", "String", "Bool"}:
            return self.type_condition(value_name, pattern), []
        return f"{value_name} == {self.expr(pattern)}", []

    def type_condition(self, value_name: str, type_name: str) -> str:
        key = normalize(type_name)
        if key == "int":
            return f"isinstance({value_name}, int) and not isinstance({value_name}, bool)"
        if key == "float":
            return f"isinstance({value_name}, float)"
        if key == "string":
            return f"isinstance({value_name}, str)"
        if key == "bool":
            return f"isinstance({value_name}, bool)"
        return "False"

    def emit_try_chain(self, block: list[Line], start_index: int, indent: int) -> tuple[list[str], int]:
        output = [self.pad(indent) + "try:"]
        output.extend(self.emit_block(block[start_index].children, indent + 1))
        index = start_index + 1
        handled = False
        if index < len(block) and starts(block[index].text, "Catch "):
            name = python_name(strip_prefix(block[index].text, "Catch "))
            output.append(self.pad(indent) + f"except Exception as {name}:")
            output.extend(self.emit_block(block[index].children, indent + 1))
            index += 1
            handled = True
        if index < len(block) and block[index].text == "Finally":
            output.append(self.pad(indent) + "finally:")
            output.extend(self.emit_block(block[index].children, indent + 1))
            index += 1
            handled = True
        if not handled:
            raise PlainError(f"Line {block[start_index].number} needs Catch or Finally after Try.")
        return output, index

    def expr(self, expression: str) -> str:
        expr = expression.strip()
        annotated = split_once_outside_quotes(expr, " as ", last=True)
        if annotated:
            expr = annotated[0]
        if starts(expr, "Need "):
            return f"_need({self.expr(strip_prefix(expr, 'Need '))})"
        if starts(expr, "Success "):
            return f"_Result(True, {self.expr(strip_prefix(expr, 'Success '))})"
        if starts(expr, "Failure "):
            return f"_Result(False, {self.expr(strip_prefix(expr, 'Failure '))})"
        if starts(expr, "Some "):
            return self.expr(strip_prefix(expr, "Some "))
        if starts(expr, "Ask"):
            prompt = strip_prefix(expr, "Ask").strip()
            if not prompt:
                return "input()"
            return f"input(str({self.expr(prompt)}) + ': ')"
        if expr == "true":
            return "True"
        if expr == "false":
            return "False"
        if expr == "nothing":
            return "None"
        if re.fullmatch(r"-?\d+(?:\.\d+)?", expr):
            return expr
        if len(expr) >= 2 and expr[0] == '"' and expr[-1] == '"':
            return self.string_expr(expr[1:-1])
        if starts(expr, "Range from "):
            match = re.match(r"Range from (.+?) to (.+?)(?: step (.+))?$", expr)
            if not match:
                raise PlainError("A range must say Range from Start to End.")
            step = self.expr(match.group(3)) if match.group(3) else "1"
            return f"_range_inclusive({self.expr(match.group(1))}, {self.expr(match.group(2))}, {step})"
        if starts(expr, "List with "):
            return "[" + ", ".join(self.expr(part) for part in split_outside_quotes(strip_prefix(expr, "List with "), " and ")) + "]"
        if expr == "Empty List":
            return "[]"
        if starts(expr, "Set with "):
            values = [self.expr(part) for part in split_outside_quotes(strip_prefix(expr, "Set with "), " and ")]
            return "{" + ", ".join(values) + "}"
        if expr == "Empty Set":
            return "set()"
        if starts(expr, "Tuple with "):
            return "(" + ", ".join(self.expr(part) for part in split_outside_quotes(strip_prefix(expr, "Tuple with "), " and ")) + ",)"
        if starts(expr, "Map with "):
            return self.map_expr(strip_prefix(expr, "Map with "))
        if expr == "Empty Map":
            return "{}"
        if starts(expr, "Teach using "):
            return self.lambda_expr(expr)
        if starts(expr, "Use "):
            return self.call_expr(strip_prefix(expr, "Use "))
        if starts(expr, "Length of "):
            return f"len({self.expr(strip_prefix(expr, 'Length of '))})"
        item_match = re.match(r"Item (.+?) of (.+)$", expr)
        if item_match:
            return f"{self.expr(item_match.group(2))}[{self.expr(item_match.group(1))}]"
        if starts(expr, "not "):
            return f"(not {self.expr(strip_prefix(expr, 'not '))})"
        for phrase, op in [(" or ", "or"), (" and ", "and")]:
            split = split_once_outside_quotes(expr, phrase)
            if split:
                return f"({self.expr(split[0])} {op} {self.expr(split[1])})"
        for phrase, op in [
            (" is at least ", ">="),
            (" is at most ", "<="),
            (" is greater than ", ">"),
            (" is less than ", "<"),
            (" is not ", "!="),
            (" is in ", "in"),
            (" is ", "=="),
        ]:
            split = split_once_outside_quotes(expr, phrase)
            if split:
                return f"({self.expr(split[0])} {op} {self.expr(split[1])})"
        for phrase, op in [
            (" plus ", "+"),
            (" minus ", "-"),
            (" times ", "*"),
            (" over ", "/"),
            (" remainder ", "%"),
        ]:
            split = split_once_outside_quotes(expr, phrase, last=True)
            if split:
                return f"({self.expr(split[0])} {op} {self.expr(split[1])})"
        return python_name(expr)

    def map_expr(self, text: str) -> str:
        entries = []
        if text:
            for piece in split_outside_quotes(text, " and "):
                split = split_once_outside_quotes(piece, " meaning ")
                if not split:
                    raise PlainError("Map entries need the word meaning.")
                entries.append(f"{self.expr(split[0])}: {self.expr(split[1])}")
        return "{" + ", ".join(entries) + "}"

    def lambda_expr(self, expr: str) -> str:
        rest = strip_prefix(expr, "Teach using ")
        split = split_once_outside_quotes(rest, " give ")
        if not split:
            raise PlainError("Anonymous teachings need the word give.")
        params_text, body = split
        params = [self.parameter_source(parameter) for parameter in parse_parameters(params_text)]
        return f"(lambda {', '.join(params)}: {self.expr(body)})"

    def call_expr(self, text: str) -> str:
        split = split_once_outside_quotes(text, " with ")
        target = split[0] if split else text
        args_text = split[1] if split else ""
        args = []
        if args_text:
            for part in split_arguments(args_text):
                named = split_once_outside_quotes(part, " be ")
                if named:
                    args.append(f"{python_name(named[0])}={self.expr(named[1])}")
                else:
                    args.append(self.expr(part))
        return f"{python_name(target)}({', '.join(args)})"

    def string_expr(self, text: str) -> str:
        if "{" not in text:
            return repr(text)
        result = ""
        cursor = 0
        for match in re.finditer(r"\{([^{}]+)\}", text):
            result += text[cursor:match.start()].replace("{", "{{").replace("}", "}}")
            result += "{" + self.expr(match.group(1)) + "}"
            cursor = match.end()
        result += text[cursor:].replace("{", "{{").replace("}", "}}")
        return "f" + repr(result)

    def pad(self, indent: int) -> str:
        return "  " * indent

    def temp_name(self, label: str) -> str:
        self.temp_index += 1
        return f"_{python_name(label)}_{self.temp_index}"


def python_name(name: str) -> str:
    cleaned = normalize(name).replace(" ", "_")
    if not cleaned:
        return "_"
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    if cleaned in {"class", "def", "for", "if", "else", "while", "return", "pass", "None", "True", "False"}:
        cleaned += "_"
    return cleaned


class LspServer:
    def __init__(self):
        self.documents: dict[str, str] = {}
        self.shutdown_requested = False

    def run(self) -> int:
        while True:
            message = self.read_message()
            if message is None:
                break
            response = self.handle(message)
            if response is not None:
                self.write_message(response)
            if self.shutdown_requested and message.get("method") == "exit":
                break
        return 0

    def read_message(self) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            text = line.decode("utf-8").strip()
            if not text:
                break
            if ":" in text:
                key, value = text.split(":", 1)
                headers[key.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            return None
        body = sys.stdin.buffer.read(length).decode("utf-8")
        return json.loads(body)

    def write_message(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8"))
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()

    def notify_diagnostics(self, uri: str) -> None:
        diagnostics = check_source(self.documents.get(uri, ""), uri, base_dir=Path.cwd())
        self.write_message({
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {"uri": uri, "diagnostics": diagnostics},
        })

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        message_id = message.get("id")
        params = message.get("params") or {}
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "capabilities": {
                        "textDocumentSync": 1,
                        "documentFormattingProvider": True,
                    },
                    "serverInfo": {"name": "twohundredseventyone", "version": VERSION},
                },
            }
        if method == "initialized":
            return None
        if method == "shutdown":
            self.shutdown_requested = True
            return {"jsonrpc": "2.0", "id": message_id, "result": None}
        if method == "exit":
            return None
        if method == "textDocument/didOpen":
            document = params.get("textDocument", {})
            uri = document.get("uri", "")
            self.documents[uri] = document.get("text", "")
            self.notify_diagnostics(uri)
            return None
        if method == "textDocument/didChange":
            document = params.get("textDocument", {})
            uri = document.get("uri", "")
            changes = params.get("contentChanges", [])
            if changes:
                self.documents[uri] = changes[-1].get("text", "")
            self.notify_diagnostics(uri)
            return None
        if method == "textDocument/formatting":
            document = params.get("textDocument", {})
            uri = document.get("uri", "")
            text = self.documents.get(uri, "")
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": max(0, len(text.splitlines())), "character": 0},
                    },
                    "newText": format_source(text),
                }],
            }
        if method == "textDocument/completion":
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "isIncomplete": False,
                    "items": lsp_completion_items(),
                },
            }
        if message_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "error": {"code": -32601, "message": f"I do not know the LSP method {method}."},
            }
        return None


def lsp() -> int:
    return LspServer().run()


def lsp_completion_items() -> list[dict[str, Any]]:
    words = [
        ("Make", "Make Name be Value"),
        ("Keep", "Keep Name be Value"),
        ("Change", "Change Name to Value"),
        ("Say", "Say Value"),
        ("Ask", "Ask Prompt"),
        ("If", "If Condition"),
        ("Otherwise if", "Otherwise if Condition"),
        ("Otherwise", "Otherwise"),
        ("Match", "Match Value"),
        ("When", "When Pattern"),
        ("Repeat for", "Repeat for Item in Items"),
        ("Repeat while", "Repeat while Condition"),
        ("Repeat forever", "Repeat forever"),
        ("Teach", "Teach Name using Parameter"),
        ("Record", "Record Name"),
        ("Object", "Object Name"),
        ("Contract", "Contract Name"),
        ("Problem", "Problem Name"),
        ("Bring", "Bring \"file.271\""),
        ("Bring Package", "Bring Package \"name/file.271\""),
        ("Need", "Need Fallible Value"),
        ("Success", "Success Value"),
        ("Failure", "Failure Value"),
        ("Ignore Result", "Ignore Result Fallible Value"),
        ("Try", "Try"),
        ("Catch", "Catch Error"),
        ("Finally", "Finally"),
        ("Spawn", "Spawn Use Work"),
        ("Await", "Await Task"),
        ("Async All", "Use Async All with Tasks"),
        ("Async Race", "Use Async Race with Tasks"),
        ("Map Get", "Use Map Get with Map and Key"),
        ("Map Put", "Use Map Put with Map and Key and Value"),
        ("Map Merge", "Use Map Merge with Left Map and Right Map"),
        ("Send", "Send Value to Channel"),
        ("Receive", "Receive from Channel"),
    ]
    return [
        {
            "label": label,
            "kind": 14,
            "insertText": insert_text,
        }
        for label, insert_text in words
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="271", description="Run twohundredseventyone programs.")
    parser.add_argument("command", nargs="?", default="help")
    parser.add_argument("target", nargs="?")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)

    command = ns.command.lower()
    if command == "help":
        print("Use: 271 run file.271")
        print("Other commands: new, doctor, check, repl, test, lint, format, docs, add, build, compile, run-compiled, emit-python, pack, lsp, serve-registry, version")
        return 0
    if command == "version":
        print(f"twohundredseventyone runner {VERSION}")
        return 0
    if command == "doctor":
        return doctor(Path(ns.target) if ns.target else None)
    if command == "new":
        if not ns.target:
            print("Plain English error: new needs a project folder.", file=sys.stderr)
            return 1
        if ns.args:
            print("Plain English error: new only needs one project folder.", file=sys.stderr)
            return 1
        return new_project(Path(ns.target))
    if command == "repl":
        return repl()
    if command == "lsp":
        return lsp()
    if command == "add":
        if not ns.target:
            print("Plain English error: add needs a package name.", file=sys.stderr)
            return 1
        remote_url = None
        if ns.args:
            if len(ns.args) == 2 and ns.args[0].lower() == "from":
                remote_url = ns.args[1]
            else:
                print("Plain English error: add understands only add Package or add Package from Url.", file=sys.stderr)
                return 1
        return add_package(ns.target, remote_url)
    if command == "serve-registry":
        port = int(ns.target or 2711)
        return serve_registry(port)
    if command in {"run", "test", "lint", "check", "format", "docs", "build", "compile", "run-compiled", "emit-python", "pack"}:
        if not ns.target:
            print(f"Plain English error: {command} needs a file or folder.", file=sys.stderr)
            return 1
        target = Path(ns.target)
        if command == "run":
            return run_file(target, ns.args)
        if command == "run-compiled":
            return run_compiled(target, ns.args)
        if command == "emit-python":
            return emit_python(target)
        if command == "pack":
            return pack_app(target)
        if command == "test":
            return run_tests(target)
        if command == "lint":
            return lint_path(target)
        if command == "check":
            return check_path(target)
        if command == "format":
            return format_path(target)
        if command == "docs":
            return docs_for(target)
        if command == "build":
            return build_project(target)
        if command == "compile":
            return compile_project(target)
    print(f"Plain English error: I do not know the command {ns.command}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
