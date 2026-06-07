# twohundredseventyone cheat sheet

## Basics

```271
Note comment
Notes
  multi-line comment

Make Number be 3
Make Name be "Ada"
Keep Max Retries be 3
Change Number to Number plus 1
Note Change cannot change Number into a different type

Say "Hello {Name}"
Make Answer be Ask "Question"
Make Missing be nothing as Maybe String
Make Maybe First be Item 0 of Names as Maybe String

Say jew
Say "jew"
```

## Blocks and control flow

```271
If Score is at least 90
  Say "great"
Otherwise if Score is at least 70
  Say "good"
Otherwise
  Say "try again"

Make Label be If Done
  "done"
Otherwise
  "open"

Match Value
  When Int named Number
    Say Number
  When Player with Name be "Ada" and Score be Score
    Say Score
  When Map with "kind" meaning "click" and "x" meaning X
    Say X
  When nothing
    Say "missing"
  When anything
    Say "other"

Type Command means Add Command or Done Command or Quit Command
Match Command
  When Add Command
    Say "add"
  When Done Command
    Say "done"
  When Quit Command
    Say "quit"

Repeat for Item in Items
  Say Item

Repeat for Number in Range from 1 to 10 step 2
  Say Number

Repeat while Running
  Skip

Repeat forever
  Stop
```

## Functions

```271
Teach Add using Left and Right
  Left plus Right

Teach Greet using Name and Punctuation be "!"
  "Hello {Name}{Punctuation}"

Teach Total using many Numbers as Int
  Use List Reduce with Numbers and 0 and Teach using Sum and Number give Sum plus Number

Make Double be Teach using Number give Number times 2
Make Result be Use Add with 2 and 3
Make Named be Use Greet with Name be "Ada"
```

## Data

```271
Make Numbers be List with 1 and 2 and 3
Make Scores be Map with "Ada" meaning 10 and "Grace" meaning 12
Make Report be Map with
  "name" meaning "Ada"
  "score" meaning 271
Make Numbers be Empty List as List of Int
Use List Add with Numbers and 271
Make Scores By Name be Empty Map as Map of String to Int
Use Map Put with Scores By Name and "Ada" and 271
Make Pair Key be List with "x" and "y"
Make Lookup be Map with Pair Key meaning "grid"
Make Maybe Score be Use Map Get with Scores and "Ada" as Maybe Int
Make Score be Use Map Get with Scores and "Ada" and Otherwise be 0
Use Map Put with Scores and "Linus" and 9
Use Map Remove with Scores and "Grace"
Make Combined be Use Map Merge with Scores and Report
Make Keys be Use Map Keys with Scores
Make Values be Use Map Values with Scores
Make Entries be Use Map Entries with Scores
Make Tags be Set with "work" and "urgent"
Make Point be Tuple with 10 and 20
Make X and Y be Point
Make Ada and Grace be Scores
Make Span be Range from 1 to 5
```

## Types and objects

```271
Type User Id means Int
Type Command means Add Command or Quit Command

Record User
  Has Id as User Id
  Has Name as String

Object Counter
  Has Value as Int
  Private Has Secret as String

  Private Teach Secret Length using Self
    Length of Secret of Self

  Teach Increase using Self
    Change Value of Self to Value of Self plus 1
    Value of Self

Object Fancy Counter extends Counter
  Has Label as String

  Teach Increase using Self
    Use Parent Increase of Self

Contract Jsonable
  Teach To Json using Self
```

## Errors, async, modules, tooling

```271
Problem Missing File
  Has Path as String

Teach Load using Path returns Result of String or Missing File
  Make Text be Need Use File Read with Path
  Success Text

Ignore Result Use Int Parse with "not a number"

Try
  Make Data be Need Use Json Parse with Text
Catch Error
  Say Use Message of Error
Finally
  Say "done"

Async Teach Fetch using Url
  Make Response be Need Await Use Http Get with Url
  Need Use Json of Response

Make Inbox be New Channel of String with Capacity be 10
Make Worker be Spawn Use Fetch with "https://example.test"
Make Tasks be List with Worker
Make All Results be Need Await Use Async All with Tasks
Make First Result be Need Await Use Async Race with Tasks
Send "ready" to Inbox
Note Sending a non-String to Inbox is an error
Make Message be Await Receive from Inbox as Maybe String
Use Close of Inbox

Bring Json
Bring Math names Clamp and Round
Bring Http as Web
Bring "math-tools.271"
Bring "math-tools.271" names Triple and Box
Bring "math-tools.271" as Tools
Bring Package "friendly-tools/greetings.271" names Friendly Greeting

Contract Labeled
  Teach Label using Self

Make Response be Need Use Http Get with "http://127.0.0.1:2710/"
```

Commands: `.\271.cmd new my-app`, `.\271.cmd doctor`, `.\271.cmd check .`,
`.\271.cmd run file.271`, `.\271.cmd repl`,
`.\271.cmd format file.271`, `.\271.cmd lint file.271`,
`.\271.cmd test tests`, `.\271.cmd add friendly-tools`,
`.\271.cmd run .\examples\browser.271`,
`.\271.cmd compile examples`, `.\271.cmd run-compiled .\.271-cache\hello.271c`,
`.\271.cmd emit-python .\examples\emitted-demo.271`,
`.\271.cmd pack .\examples\hello.271`, `.\271.cmd serve-registry 2711`,
`.\271.cmd lsp`, `.\271.cmd version`.
