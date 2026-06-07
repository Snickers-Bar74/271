# twohundredseventyone language spec

Version: plain-English design draft 2

twohundredseventyone is a general-purpose language for scripts, tools, servers,
applications, and safe concurrent systems. Its command name is `271`. Source
files use `.271`.

The guiding test is simple: a beginner should be able to read a program aloud
and hear what it does. The canonical variable example is:

```271
Make Number be 3
```

## 1. Philosophy

1. One concept has one spelling.
2. Keywords are plain English words.
3. Code reads like short sentences.
4. Blocks are exactly 2 spaces deeper than their parent line.
5. No braces, semicolons, or line-ending punctuation.
6. Type annotations are optional unless absence would be ambiguous.
7. Absence is explicit.
8. Failure is explicit.
9. Silent wrong results are never acceptable.

The language has one loop construct: `Repeat`. It handles collection loops,
range loops, condition loops, and forever loops.

## 2. Text, names, and indentation

### Keyword style

Official examples write keywords in Title Case: `Make`, `Keep`, `Teach`,
`Repeat`, `Say`. Keywords are case-insensitive, but the formatter rewrites them
to Title Case.

### Name phrases

Programmer-defined names are English name phrases: one or more capitalized
words.

```271
Make User Name be "Ada"
Make Retry Count be 0
Teach Load User using User Id
```

Name phrases end at reserved words such as `be`, `using`, `with`, `and`,
`returns`, `of`, or the end of the line.

Primitive values are lowercase:

```271
true
false
nothing
```

### Indentation

Indentation defines blocks. Every nested block is exactly 2 spaces deeper.

```271
If Ready
  Say "ready"
Otherwise
  Say "not ready"
```

Plain English compiler error:

```text
This block is indented with 4 spaces. Use exactly 2 spaces here.
```

### Comments

Single-line comments use `Note`.

```271
Note This value is kept for this request only
```

Multi-line comments use a `Notes` block.

```271
Notes
  This parser is intentionally strict.
  The formatter will not guess what the author meant.
```

## 3. Making values

### Variables

Variables are made and assigned in one line.

```271
Make Number be 3
Make Name be "Ada"
Make Ready be true
```

Variables are changed with `Change`.

```271
Change Number to Number plus 1
```

`Change` preserves the inferred or declared type of the variable. Fields also
keep their declared type.

```271
Make Count be 1
Change Count to Count plus 1

Record Profile
  Has Name as String

Make Guest be New Profile with Name be "Ada"
Change Name of Guest to "Ada Lovelace"
```

### Constants

Constants use the visually distinct keyword `Keep`.

```271
Keep Max Retries be 3
Keep Api Url be "https://api.example.test"
```

Kept values cannot be changed.

### Optional annotations

Annotations use `as` and are optional unless the value is `nothing`.
The checker catches clear annotation mismatches before runtime, while the
runner still checks annotations dynamically when values are produced later.

```271
Make Count be 0
Make Count be 0 as Int
Make Middle Name be nothing as Maybe String
```

## 4. Primitive values

Primitive types are:

- `Int`
- `Float`
- `String`
- `Bool`
- `Byte`

The absence value is `nothing`. It can only appear in a type that allows
absence, such as `Maybe String`.

Any stored value that can be `nothing` must say `as Maybe ...` explicitly. This
includes direct `nothing`, `Some Value`, safe `Item` access, and receiving from a
channel that may close.

```271
Make Missing be nothing as Maybe String
Make Present be Some "Ada" as Maybe String
Make Maybe First be Item 0 of Names as Maybe String
```

Booleans are exactly `true` and `false`. There is no truthy or falsy behavior.

Integer overflow is an error. Division by zero is an error. Numeric narrowing
must be explicit.

## 5. Strings

Single-line strings use quotes. Interpolation uses `{English Expression}`.

```271
Make Name be "Ada"
Say "Hello {Name}"
```

Multi-line strings use a `Text` block.

```271
Make Message be Text
  Hello {Name}
  Your task is ready.
Say Message
```

## 6. Collections

Collections use English constructor forms. Single-line forms use `and` between
items.

```271
Make Numbers be List with 1 and 2 and 3
Make Scores be Map with "Ada" meaning 10 and "Grace" meaning 12
Make Tags be Set with "work" and "urgent"
Make Point be Tuple with 10 and 20
Make Span be Range from 1 to 10 step 2
```

Empty collections have explicit names.

```271
Make Items be Empty List
Make Lookup be Empty Map
Make Seen be Empty Set
```

Typed collections keep their declared item, key, and value types when helper
calls update them. A `List of Int` rejects a string passed to `List Add`, a
`Set of String` rejects an integer passed to `Set Add`, and a
`Map of String to Int` checks both the key and the value passed to `Map Put`.

```271
Make Numbers be Empty List as List of Int
Use List Add with Numbers and 271

Make Scores be Empty Map as Map of String to Int
Use Map Put with Scores and "Ada" and 10
```

Large collections can use an indented block.

```271
Make Task Data be Map with
  "id" meaning Id of Task
  "title" meaning Title of Task
  "done" meaning Done of Task
```

Lists are ordered and dynamic. Maps hold key-value pairs and may use any
language value as a key, including lists, tuples, records, and other maps. Sets
hold unique values. Tuples are fixed and immutable. Ranges include the start and
include the end if the step lands on it.

Collection access returns a maybe value, never a silent wrong value.

```271
Make Maybe First be Item 0 of Items as Maybe String
```

Map lookup also returns a maybe value unless an explicit fallback is provided.

```271
Make Maybe Score be Use Map Get with Scores and "Ada" as Maybe Int
Make Score be Use Map Get with Scores and "Ada" and Otherwise be 0
```

## 7. Expressions

Operators are words.

```271
Total plus Tax
Count minus 1
Width times Height
Total over Count
Number remainder 10
```

Comparisons are also words.

```271
Age is at least 18
Name is "Ada"
Name is not "Grace"
Score is greater than High Score
Tag is in Tags
Ready and Connected
not Done
```

Conditions must produce `Bool`.

Field access uses `of`.

```271
Name of User
Value of Counter
```

## 8. Terminal input and output

`Say` prints any value.

```271
Say "Hello world"
Say List with 1 and 2 and 3
```

`Ask` reads one line from the terminal. It accepts an optional prompt and
returns `String`.

```271
Make Name be Ask "Name"
```

## 9. Control flow

### If

```271
If Score is at least 90
  Say "A"
Otherwise if Score is at least 80
  Say "B"
Otherwise
  Say "keep practicing"
```

`If` can produce a value when all branches produce compatible values.

```271
Make Label be If Done
  "done"
Otherwise
  "open"
```

### Match

`Match` supports values, types, maybe values, list patterns, map patterns,
record/object field patterns, exhaustive union matching, and a final fallback.

```271
Match Value
  When nothing
    Say "nothing"
  When Int named Number
    Say "number {Number}"
  When String named Words
    Say "text {Words}"
  When anything
    Say "something else"
```

Maybe values unwrap with `Some`.

```271
Make Name be Match Maybe Name
  When Some Actual Name
    Actual Name
  When nothing
    "world"
```

List patterns can bind the rest with `many`.

```271
Match Words
  When List starting with "add" and many Title Words
    Say Use String Join with Title Words and By be " "
  When anything
    Say "unknown"
```

Map patterns use `meaning`, just like map literals.

```271
Match Event
  When Map with "kind" meaning "click" and "x" meaning X
    Say "clicked at {X}"
  When anything
    Say "unknown event"
```

Union types must handle every variant unless they use `When anything`.

```271
Type Command means Add Command or Done Command or Quit Command

Match Command
  When Add Command with Title be Title
    Say "add {Title}"
  When Done Command
    Say "done"
  When Quit Command
    Say "quit"
```

Record and object field patterns use `with` and `be`.

```271
Match Player
  When Player with Name be "Ada" and Score be Score
    Say "Ada scored {Score}"
  When Player with Score be Int named Points
    Say "score was {Points}"
```

Field patterns may contain nested patterns such as `Some Value`, `Success Text`,
`Int named Number`, and `List with Item`.

Matches over unions and maybe values must be exhaustive.

Plain English compiler error:

```text
This match does not handle Quit Command.
```

### Repeat

Every loop starts with `Repeat`.

Collection loop:

```271
Repeat for Item in Items
  Say Item
```

Range loop:

```271
Repeat for Number in Range from 1 to 5
  Say Number
```

Index loop:

```271
Repeat for Index in Indices of Items
  Say Item Index of Items
```

Condition loop:

```271
Repeat while Running
  Say "tick"
```

Forever loop:

```271
Repeat forever
  Say "until stop"
  Stop
```

`Stop` exits the nearest repeat. `Skip` starts the next iteration.

There are no standalone `for`, `while`, or `loop` constructs.

## 10. Functions

Functions use one keyword: `Teach`.

```271
Teach Add using Left and Right
  Left plus Right
```

The last value is the return value. There is no `return` keyword.

Optional parameter and return annotations:

```271
Teach Add using Left as Int and Right as Int returns Int
  Left plus Right
```

Default parameters:

```271
Teach Greet using Name and Punctuation be "!"
  "Hello {Name}{Punctuation}"
```

Variadic parameters:

```271
Teach Total using many Numbers as Int
  Use List Reduce with Numbers and 0 and Teach using Sum and Number give Sum plus Number
```

Calls start with `Use`.

```271
Make Sum be Use Add with 2 and 3
Make Message be Use Greet with Name be "Ada" and Punctuation be "?"
Make Now be Use Time Now
```

Teachings can be stored, passed to other teachings, and returned.

```271
Make Double be Teach using Number give Number times 2
Make Values be Use List Map with List with 1 and 2 and 3 and Double
```

Anonymous functions use the same keyword and the one-line `give` form.

```271
Make Open Tasks be Use List Filter with Tasks and Teach using Task give not Done of Task
```

Closures capture surrounding values.

```271
Teach Greater Than using Limit
  Teach using Value give Value is greater than Limit
```

Async functions keep the same syntax with an `Async` modifier.

```271
Async Teach Fetch Json using Url
  Make Response be Need Await Use Http Get with Url
  Need Use Json of Response
```

## 11. Types

Types are inferred by default. Annotations are optional.

```271
Make Count be 0
Make Count be 0 as Int
```

Generic types use words.

```271
List of String
Map of String to Int
Set of String
Tuple of Int and Int
Maybe User
Result of User or App Error
Channel of Message
```

Type aliases:

```271
Type User Id means Int
```

Union types:

```271
Type Command means Add Command or Done Command or List Command or Quit Command
```

Nullable values must be explicit:

```271
Make Maybe User be nothing as Maybe User
Make Present User be Some User as Maybe User
```

## 12. Records

Records are lightweight value types with named fields.

```271
Record User
  Has Id as Int
  Has Name as String
  Has Email as Maybe String
```

Record constructors are generated from field names.

```271
Make User be New User with Id be 1 and Name be "Ada" and Email be nothing
```

Destructuring uses `and`.

```271
Make Id and Name and Email be User
```

Lists and tuples destructure by position. Sets destructure in deterministic text
order. Maps, records, and objects destructure by matching the requested names.
The count or requested names must be correct; dropping extra values silently is
not allowed.

```271
Make First and Second be Tuple with 7 and 8
Make Ada and Grace be Map with "Ada" meaning 10 and "Grace" meaning 12
Make Name and Score be Player
```

Records compare by value.

## 13. Objects and contracts

Objects hold state and behavior.

```271
Object Counter
  Has Value as Int

  Teach Increase using Self
    Change Value of Self to Value of Self plus 1
    Value of Self
```

Constructors are generated from field names.

```271
Make Counter be New Counter with Value be 0
```

Everything is public by default. Use `Private` for private fields or teachings.
Private fields and private teachings may be used by methods on the declaring
object, but outside code cannot read, change, or call them. Constructors still
accept private field names because they are generated from all field names.

```271
Object Secret
  Private Has Token as String

  Private Teach Reveal Token using Self
    Token of Self
```

Objects support single inheritance.

```271
Object Admin extends User
  Has Permissions as Set of String
```

Inherited public fields and methods are available on child objects. Private
members remain private to the object that declared them.

Child objects may override parent methods. Inside an object teaching, the child
can call the parent implementation with `Use Parent`.

```271
Object Account
  Has Name as String

  Teach Label using Self returns String
    Name of Self

Object Premium Account extends Account
  Has Level as Int

  Teach Label using Self returns String
    "{Use Parent Label of Self} level {Level of Self}"
```

`Parent` is only available inside an object teaching. It searches the parent
chain for public methods and keeps private teachings private to the declaring
object.

Contracts describe required behavior.

```271
Contract Jsonable
  Teach To Json using Self
```

Records and objects can follow contracts.

```271
Object User Store follows Jsonable
  Has Users as List of User

  Teach To Json using Self
    Use Json Serialize with Users of Self
```

## 14. Modules and packages

Every file is a module.

Bring a whole module:

```271
Bring Json
```

Bring another source file:

```271
Bring "math-tools.271"
```

Bring a source file as a namespace:

```271
Bring "math-tools.271" as Tools
Make Number be Use Triple of Tools with 9
```

Bring specific names from a source file:

```271
Bring "math-tools.271" names Triple and Box
Make Number be Use Triple with 9
```

Bring specific names:

```271
Bring Math names Clamp and Round
```

Bring with an alias:

```271
Bring Http as Web
```

Add packages with one command:

```text
.\271.cmd add friendly-tools
.\271.cmd add friendly-tools from http://127.0.0.1:2711
```

The local package manager installs from `registry/` into `packages/`, then
writes `271.package` and `271.lock`. The runner can also serve the local
registry over HTTP:

```text
.\271.cmd serve-registry 2711
```

Installed packages can be brought into a program:

```271
Bring Package "friendly-tools/greetings.271" names Friendly Greeting
Say Use Friendly Greeting with "Ada"
```

## 15. Standard library

The standard library is built in and needs no configuration.

Math:

```271
Use Math Sqrt with Number
Use Math Clamp with Value and Low and High
```

String:

```271
Use String Trim with Text
Use String Lower with Text
Use String Split with Text and By be " "
Use String Join with Parts and By be ", "
Use String Contains with Text and "needle"
```

List:

```271
Use List Map with Items and Teach using Item give Name of Item
Use List Filter with Items and Teach using Item give Done of Item
Use List Reduce with Numbers and 0 and Teach using Total and N give Total plus N
Use List Sort with Items and By be Teach using Item give Name of Item
Use List Zip with Names and Scores
Make First and Second be List with 1 and 2
```

Map:

```271
Use Map Has with Settings and "theme"
Make Maybe Theme be Use Map Get with Settings and "theme" as Maybe String
Make Theme be Use Map Get with Settings and "theme" and Otherwise be "plain"
Use Map Put with Settings and "theme" and "bright"
Use Map Remove with Settings and "old"
Make Combined be Use Map Merge with Settings and Overrides
Use Map Keys with Settings
Use Map Values with Settings
Use Map Entries with Settings
```

File:

```271
Need Use File Read with Path
Need Use File Write with Path and Text
Need Use File Delete with Path
Repeat for Entry in Use File Walk with Folder
  Say Path of Entry
```

Http:

```271
Make Response be Need Await Use Http Get with Url
Make Posted be Need Await Use Http Post with Url and Json be Body
Make Data be Need Use Json of Response
```

The local runner implements `Http Get`, `Http Post`, and `Http Serve`.

Desktop:

```271
Make Window be Need Use Desktop Browser with Title be "271 Browser" and Home be "https://example.com"
```

The current Windows runner opens a native Windows Forms browser window with an
address bar and navigation controls. It does not use Tkinter.

Json:

```271
Make Value be Need Use Json Parse with Text
Make Text be Need Use Json Serialize with Value
```

Time:

```271
Make Now be Use Time Now
Make Label be Use Time Format with Now and "yyyy-mm-dd"
Await Use Time Sleep with Seconds be 1
```

OS:

```271
Make Args be Use OS Args
Make Home be Use OS Env with "HOME"
Use OS Exit with 0
```

Regex:

```271
Use Regex Match with Text and Pattern be "^[a-z]+$"
Use Regex Replace with Text and Pattern be "x" and With be "y"
```

Async:

```271
Make Tasks be List with Task A and Task B
Make Both be Need Await Use Async All with Tasks
Make First be Need Await Use Async Race with Tasks
```

## 16. Error handling

Fallible work returns `Result of Success Type or Error Type`.

```271
Result of String or File Error
```

Success and failure values use `Success` and `Failure`.

```271
Success "done"
Failure Missing File with Path be "tasks.json"
```

Custom errors use `Problem`.

```271
Problem Missing File
  Has Path as String

  Teach Message using Self
    "Could not find {Path of Self}"
```

`Need` unwraps a success. If it sees a failure, it sends that failure upward to
the nearest `Catch` or to the current teaching result.

```271
Teach Load using Path returns Result of String or File Error
  Make Text be Need Use File Read with Path
  Success Text
```

A `Result` may not be silently ignored. Store it with `Make`, inspect it with
`Match`, propagate it with `Need`, or explicitly discard it.

```271
Ignore Result Use Int Parse with "not a number"
```

`Try`, `Catch`, and `Finally` are indentation-based.

```271
Try
  Make Text be Need Use File Read with "input.txt"
  Say Text
Catch Error
  Say Use Message of Error
Finally
  Say "finished"
```

`Finally` always runs.

All compiler, runtime, linter, test, package, and server errors must be plain
English. Runtime errors include a plain-English trace when a failure crosses
teachings or nested lines.

## 17. Concurrency

Async teachings return tasks. `Await` waits for a task.

```271
Async Teach Get Title using Url
  Make Response be Need Await Use Http Get with Url
  Use Text of Response
```

`Spawn` starts background work and returns a task handle.

```271
Make Worker be Spawn Use Refresh Cache
```

`Async All` returns a combined task that waits for every task and succeeds with
a list of values. `Async Race` returns a combined task that succeeds with the
first finished value. If any gathered task returns `Failure`, the combined task
returns that failure.

```271
Make Task A be Spawn Use Fetch with "/a"
Make Task B be Spawn Use Fetch with "/b"
Make Tasks be List with Task A and Task B
Make Both be Need Await Use Async All with Tasks
Make First be Need Await Use Async Race with Tasks
```

Channels pass values safely between tasks. The declared channel type is checked
before run when the checker can see it and at runtime when values cross task
boundaries.

```271
Make Inbox be New Channel of String with Capacity be 10
Send "reload" to Inbox
Make Message be Await Receive from Inbox as Maybe String
```

Receiving from a closed channel returns `nothing`.

## 18. Testing

Tests are normal teachings marked with `Test`.

```271
Test Teach Adding Numbers
  Expect Use Add with 2 and 3 is 5
```

Plain English failure:

```text
Expected Add with 2 and 3 to be 5, but it was 4.
```

## 19. Tooling

The design target is one built-in tool. The local folder already includes a
working runner named `271.py` and Windows launchers named `271.cmd` and
`271.ps1`.

```text
.\271.cmd new app
.\271.cmd doctor
.\271.cmd check app.271
.\271.cmd run app.271
.\271.cmd compile app.271
.\271.cmd run-compiled .\.271-cache\app.271c
.\271.cmd emit-python app.271
.\271.cmd pack app.271
.\271.cmd repl
.\271.cmd lint app.271
.\271.cmd test tests
.\271.cmd version
```

The full language goal still includes a richer formatter, remote package
registry and optimized build output. The current runner already supports
running with semantic preflight, testing, linting, a simple formatter, docs generation, local and HTTP
package installation, self-contained runnable build output, AST-based compile
cache artifacts, semantic preflight checks with conservative static type
inference, and a readable Python source emitter covering variables, destructuring,
functions, defaults, variadics, loops, matches, maps, sets, tuples, results, and
try/catch/finally. It also supports packaged Python zipapps, a REPL, a
JSON-RPC stdio LSP server with diagnostics, formatting, and completions,
checked annotations, source-file modules, package modules, import aliases,
specific-name imports, enforced contracts, enforced private fields and private
teachings, single inheritance with parent method calls, safe destructuring,
explicit `Maybe` checks, ignored-`Result` checks, exhaustive union `Match` checks, checked channel messages, map and field patterns in `Match`, maps with any-value keys and checked lookup, expression-style `If` assignments, multi-line `Map with` entries, spawn/await, channels, HTTP client
calls, fresh project scaffolding, doctor checks, a preloaded `jew` alias that
says `271`, type-safe mutation for variables and fields, plain-English runtime
traces, and a working local HTTP server.

## 20. Safety rules

- Out-of-bounds item access and missing map lookup return `nothing`.
- Conditions must be `Bool`.
- Division by zero is an error.
- Integer overflow is an error.
- Numeric narrowing must be explicit.
- Maybe values must be matched or safely transformed.
- `Change` cannot change a variable or field to an incompatible type.
- Union matches must be exhaustive or include `When anything`.
- IO, HTTP, JSON, and regex failures return `Result`.
- Ignoring a `Result` is a check and runtime error unless written as `Ignore Result`.
- Channels reject messages outside their declared type.
- Data races are compile-time errors.

## 21. Feature justification

| Feature | Reason it exists |
| --- | --- |
| `Make` | One readable way to create a variable. |
| `Keep` | One visually distinct way to create a constant. |
| `Change` | Makes mutation visible. |
| `Say` | One print keyword for every value. |
| `Ask` | One terminal input keyword. |
| `nothing` | One absence value. |
| `Maybe` | Prevents accidental absence use. |
| `Result` | Makes failure explicit and composable. |
| `Need` | Propagates failure without punctuation. |
| `Ignore Result` | Makes deliberate failure discard visible. |
| `Try/Catch/Finally` | Handles failure locally with guaranteed cleanup. |
| `Match` | Makes branching on values, shapes, and types readable. |
| `Repeat` | One loop construct for every loop shape. |
| `Teach` | One way to define named and anonymous behavior. |
| `Record` | Lightweight value grouping. |
| `Object` | Stateful objects with methods. |
| `Contract` | Behavior requirements without complex inheritance. |
| `Spawn` and channels | Safe concurrent work without shared mutable data races. |
| Built-in tooling | Beginners should not assemble a toolchain before learning. |

## 22. Grammar sketch

This sketch describes the language shape rather than every parser detail.

```text
file          = top level line*
block         = line indented block
variable      = "Make" name phrase "be" expression
constant      = "Keep" name phrase "be" expression
assignment    = "Change" place "to" expression
teaching      = ["Async"] ["Test"] "Teach" name phrase ["using" parameters] ["returns" type] block
anonymous     = "Teach" "using" parameters "give" expression
if            = "If" condition block ("Otherwise if" condition block)* ["Otherwise" block]
match         = "Match" expression ("When" pattern block)+
repeat        = "Repeat" repeat header block
try           = "Try" block ["Catch" name phrase block] ["Finally" block]
call          = "Use" name phrase ["with" arguments]
```

## 23. Hello world

```271
Say "Hello world"
```

Run it:

```text
.\271.cmd run hello.271
```
