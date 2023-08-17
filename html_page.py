# HTML Page contents
page1 = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="ie-edge">
    <title>LoPy4</title>
    <!-- <link rel="shortcut icon" href="#" type="image/x-icon"> -->
    <link rel="icon" href="data:,">

</head>
<body onload="init();">
    <header>
        <div>
            <h1>BLE/WiFi App</h1>
        </div>
    </header>
    <div class="container">
        <div>
            <ul class="list-group" id="messageList">
"""

page2 = """
            </ul>
            <form onsubmit="event.preventDefault();">
                <br>
                <input type="text" name="NAME" placeholder="Set your Username"
                    required
                    id="username"
                    onkeyup="enableBtn()"
                    maxlength="10">
                <span> Byte size: </span><span id="byteSize">0</span>
                <input type="text" class="message-input"
                    id="myinp"
                    required
                    onkeyup="enableBtn()">
                <button disabled
                    onclick="sendMessage()"
                    class="send-message-button"
                    id="sendBtn">Send</button>
            </form>
        </div>
    </div>
    <script>
        myinp.onkeyup=myinp.onblur=myinp.onpaste= function vld(e){
            enableBtn();
            var inp=e.target;
            document.getElementById('byteSize').innerHTML = new Blob([inp.value]).size;
            if (new Blob([inp.value]).size > 200) {
                for (i=0; i <= inp.value.length; i++) {
                    if(new Blob([inp.value.slice(0,i)]).size <= 200) {
                        continue;
                    } else {
                        alert("Maximum byte size of 200 bytes is exceeded")
                        inp.value = inp.value.slice(0, i-1)
                        break
                    }
                }
            }
        }

        function enableBtn() {
            if(document.getElementById("username").value==="" ||
                document.getElementById("myinp").value==="" ) {
                document.getElementById('sendBtn').disabled = true;
            } else {
                document.getElementById('sendBtn').disabled = false;
            }
       }

        function sendMessage() {
            var username = document.getElementById("username").value;
            document.getElementById("username").disabled = true;
            var message = document.getElementById("myinp").value;
            document.getElementById("myinp").value = "";
            ws.send(username + "> " + message);
        }

        var ws;

        function init() {

            ws = new WebSocket("ws://192.168.4.1:80");

            ws.onopen = function() {
                console.log('WebSocket connection established');
            }

            ws.onmessage = function(e) {
                console.log('Received message:', e);
                var ul = document.getElementById("messageList");
                var li = document.createElement("li");
                li.className = "list-group-item";
                li.appendChild(document.createTextNode(e.data));
                ul.appendChild(li);
                ul.scrollTo(0, ul.scrollHeight);
            };

            ws.onclose = function() {
                console.log("onclose");
            };

            ws.onerror = function(e) {
                console.log("onerror");
                console.log(e)
            };
        }

    </script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-size: 16px;
            font-family:'Trebuchet MS';
        }
        h1 {
            font-size: 32px;
            color:aliceblue;
            text-align: center;
        }
        header {
            background-color:blueviolet;
            padding: 20px;
            box-shadow: 0px 2px 5px rgba(0, 0, 0, 0.122);
            margin-bottom: 16px;
        }
        .container {
            max-width: 600px;
            width: 100%;
            margin: auto;
            padding: 0px 16px;
        }
        .message-input {
            display: block;
            width: 100%;
            margin-bottom: 8px;
            border-radius: 6px;
            padding: 10px;
            border: 2px solid blueviolet;
            font-size: 25px;
            margin-top: 20px;
        }
        .send-message-button {
            display: block;
            width: 100%;
            max-width: 300px;
            margin: auto;
            background-color: white;
            border: 2px solid blueviolet;
            border-radius: 6px;
            padding: 10px;
            transition: all 0.3s;
            font-size: 20px;
        }
        .send-message-button:hover {
            background-color:blueviolet;
            color:aliceblue;
        }
        .list-group {
            margin-top: 12px;
            height: 60vh;
            overflow: scroll;
            border: 2px solid blueviolet;
            border-radius: 8px;
            padding: 8px;
        }
        .list-group-item {
            margin-bottom: 4px;
            list-style: none;
            border-bottom: 1px solid blueviolet;
            padding: 6px;
        }
        .message-title{
            margin: 10px 0px;
            text-align: center;
        }
    </style>
</body>
</html>
"""
# HTML Page contents END
