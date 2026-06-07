# Hello world to REST API in 5 steps

## 1. Hello world

Create `hello.271`.

```271
Say "Hello world"
```

Run it.

```text
.\271.cmd run hello.271
```

## 2. Read input and print interpolated text

```271
Make Name be Ask "Name"
Say "Hello {Name}"
```

## 3. Create a teaching and a record

```271
Record Greeting
  Has Name as String
  Has Message as String

Teach Make Greeting using Name
  New Greeting with Name be Name and Message be "Hello {Name}"

Make Greeting be Use Make Greeting with Ask "Name"
Say Message of Greeting
```

## 4. Save and load JSON

```271
Bring File
Bring Json

Record Greeting
  Has Name as String
  Has Message as String

Teach Save Greeting using Greeting
  Make Text Value be Need Use Json Serialize with Greeting
  Need Use File Write with "greeting.json" and Text Value
  Success "saved"

Teach Load Greeting returns Result of Greeting or File Error
  Make Text Value be Need Use File Read with "greeting.json"
  Need Use Json Parse with Text Value

Try
  Make Greeting be New Greeting with Name be "Ada" and Message be "Hello Ada"
  Need Use Save Greeting with Greeting
  Say Need Use Load Greeting
Catch Error
  Say Use Message of Error
```

## 5. Build a tiny REST API

Create `server.271`.

```271
Bring Http
Bring Json
Bring Time

Record Greeting
  Has Name as String
  Has Message as String
  Has Created At as String

Teach Make Greeting using Name
  Make Now be Use Time Now
  Make Created be Use Time Format with Now and "yyyy-mm-dd hh:ss"
  Make Message be "Hello {Name}"
  New Greeting with Name be Name and Message be Message and Created At be Created

Async Teach Handle using Request
  Match Request
    When Http Get with Path be "/"
      Use Http Response with Text be "twohundredseventyone API"
    When Http Get with Path be "/hello"
      Make Actual Name be Match Query "name" of Request
        When Some Name
          Name
        When nothing
          "world"
      Make Greeting be Use Make Greeting with Actual Name
      Use Http Response with Json be Greeting
    When Http Post with Path be "/hello"
      Make Body be Need Await Use Json of Request
      Make Greeting be Use Make Greeting with Name of Body
      Use Http Response with Status be 201 and Json be Greeting
    When anything
      Use Http Response with Status be 404 and Text be "Not found"

Use Http Serve with Port be 2710 and Handle be Handle
```

Run it.

```text
.\271.cmd run .\examples\server.271
```

Try it.

```text
curl http://localhost:2710/hello?name=Ada
curl -X POST http://localhost:2710/hello -d "{\"name\":\"Grace\"}"
```
