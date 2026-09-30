// Reproductor nativo del visor de videos (ver native_video.py).
// Imita el <video controls> de la página: controles que se ocultan solos,
// clic = pausa, doble clic = modo cine, flechas = adelantar/retroceder.
import QtQuick
import QtMultimedia
import QtQuick.Effects

Item {
    id: root
    focus: true

    signal mediaEvent(string json)

    property bool cover: false          // object-fit: cover (modo cine)
    property var holes: []              // [[x, y, w, h], ...] en px del widget
    property bool cinema: false
    property string title: ""
    property real pendingStart: 0
    property bool active: false
    property bool pointerActive: false  // el ratón se movió hace poco
    property bool scrubbing: false
    property real scrubPos: 0
    readonly property bool playing: player.playbackState === MediaPlayer.PlayingState
    readonly property real positionMs: player.position
    readonly property bool controlsShown: active && (!playing || pointerActive || scrubbing)

    function send(obj) { root.mediaEvent(JSON.stringify(obj)) }

    function load(url: string, start: real, muted: bool) {
        pendingStart = start
        audio.muted = muted
        lastTimeSent = -1
        active = true
        player.source = url
        player.play()
        root.forceActiveFocus()
        poke()
    }

    function stopPlayback() {
        active = false
        player.stop()
        player.source = ""
    }

    function command(cmd: string) {
        if (cmd === "pause") player.pause()
        else if (cmd === "resume") player.play()
        else if (cmd === "toggle") togglePlay()
        else if (cmd === "stop") stopPlayback()
        else if (cmd === "focus") root.forceActiveFocus()
    }

    function togglePlay() {
        if (playing) { player.pause(); flash("❚❚") }
        else { player.play(); flash("▶") }
    }

    function seekTo(ms) {
        const d = player.duration
        player.position = Math.max(0, d > 0 ? Math.min(ms, d - 250) : ms)
        poke()
    }

    function seekBy(sec) {
        seekTo(player.position + sec * 1000)
        flash((sec > 0 ? "+" : "−") + Math.abs(sec) + " s")
    }

    function setVolume(v) {
        audio.volume = Math.max(0, Math.min(1, v))
        if (audio.volume > 0) audio.muted = false
        flash("🔊 " + Math.round(audio.volume * 100) + "%")
    }

    function fmt(ms) {
        let s = Math.max(0, Math.floor(ms / 1000))
        const h = Math.floor(s / 3600); s -= h * 3600
        const m = Math.floor(s / 60); s -= m * 60
        const ss = (s < 10 ? "0" : "") + s
        return h > 0 ? h + ":" + (m < 10 ? "0" : "") + m + ":" + ss : m + ":" + ss
    }

    // Mostrar controles y avisar a la página (modo cine: revela la cabecera).
    function poke() {
        if (!pointerActive) send({type: "activity", active: true})
        pointerActive = true
        idleTimer.restart()
    }

    function flash(text) {
        flashText.text = text
        flashBox.opacity = 1
        flashTimer.restart()
    }

    property real lastTimeSent: -1

    MediaPlayer {
        id: player
        videoOutput: vout
        audioOutput: AudioOutput { id: audio }

        onPositionChanged: (pos) => {
            const t = pos / 1000
            if (Math.abs(t - root.lastTimeSent) >= 1) {
                root.lastTimeSent = t
                root.send({type: "time", time: t, duration: duration / 1000})
            }
        }
        onPlaybackStateChanged: {
            if (playbackState !== MediaPlayer.StoppedState)
                root.send({type: playbackState === MediaPlayer.PlayingState ? "playing" : "paused", time: position / 1000})
        }
        onMediaStatusChanged: {
            if ((mediaStatus === MediaPlayer.LoadedMedia || mediaStatus === MediaPlayer.BufferedMedia) && root.pendingStart > 0) {
                const start = root.pendingStart
                root.pendingStart = 0
                if (!duration || start < duration / 1000 - 1) position = start * 1000
            } else if (mediaStatus === MediaPlayer.EndOfMedia && root.active) {
                root.send({type: "ended"})
            }
        }
        onErrorOccurred: (error, errorString) => root.send({type: "error", message: errorString || "No se pudo reproducir el video"})
    }

    // ─── Botón circular reutilizable ─────────────────────────────────────────
    component IconButton: Rectangle {
        id: btn
        property string icon: ""
        property string tip: ""
        property int size: 36
        signal activated()
        width: size; height: size; radius: size / 2
        color: area.containsMouse ? "#33ffffff" : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }
        Text { anchors.centerIn: parent; text: btn.icon; color: "white"; font.pixelSize: btn.size * 0.48 }
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onPositionChanged: root.poke()
            onClicked: { btn.activated(); root.forceActiveFocus(); root.poke() }
        }
    }

    // Todo lo visible va aquí dentro: así se pueden recortar los huecos (ver maskItem).
    Item {
        id: content
        anchors.fill: parent
        layer.enabled: root.holes.length > 0
        layer.effect: MultiEffect {
            maskEnabled: true
            maskInverted: true
            maskSource: maskItem
            maskThresholdMin: 0.5
            maskSpreadAtMin: 0
        }

        Rectangle { anchors.fill: parent; color: "black" }

        VideoOutput {
            id: vout
            anchors.fill: parent
            fillMode: root.cover ? VideoOutput.PreserveAspectCrop : VideoOutput.PreserveAspectFit
        }

        Timer {
            id: idleTimer
            interval: 2500
            onTriggered: {
                root.pointerActive = false
                root.send({type: "activity", active: false})
            }
        }

        Timer { id: clickTimer; interval: 220; onTriggered: root.togglePlay() }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton
            cursorShape: root.controlsShown ? Qt.ArrowCursor : Qt.BlankCursor
            onPositionChanged: root.poke()
            onClicked: (m) => {
                root.forceActiveFocus()
                // Con los controles ocultos, un clic en la franja inferior solo los muestra.
                if (!root.controlsShown && m.y > height - bottomBar.height) { root.poke(); return }
                clickTimer.restart()
            }
            onDoubleClicked: { clickTimer.stop(); root.send({type: "action", action: "cinema"}) }
            onWheel: (wheel) => root.setVolume(audio.volume + (wheel.angleDelta.y > 0 ? 0.05 : -0.05))
        }

        // ─── Aviso central (pausa, +5 s, volumen) ────────────────────────────────
        Rectangle {
            id: flashBox
            anchors.centerIn: parent
            width: Math.max(84, flashText.implicitWidth + 36); height: 64; radius: 32
            color: "#99000000"
            opacity: 0
            Behavior on opacity { NumberAnimation { duration: 250 } }
            Text { id: flashText; anchors.centerIn: parent; color: "white"; font.pixelSize: 24; font.bold: true }
            Timer { id: flashTimer; interval: 600; onTriggered: flashBox.opacity = 0 }
        }


        // ─── Título (arriba) y acciones rápidas ──────────────────────────────────
        Rectangle {
            id: topShade
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: root.cinema ? 110 : 72
            opacity: root.controlsShown ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            gradient: Gradient {
                GradientStop { position: 0; color: "#aa000000" }
                GradientStop { position: 1; color: "transparent" }
            }
            Text {
                // En modo cine la cabecera de la página ocupa la franja superior.
                anchors { left: parent.left; leftMargin: root.cinema ? 22 : 16; right: actions.left; rightMargin: 12; top: parent.top; topMargin: root.cinema ? 60 : 12 }
                text: root.title
                color: "white"; font.pixelSize: 15; font.bold: true
                elide: Text.ElideRight
            }
            Row {
                id: actions
                anchors { right: parent.right; rightMargin: 10; top: parent.top; topMargin: root.cinema ? 54 : 6 }
                spacing: 4
                IconButton { icon: "🏷️"; onActivated: root.send({type: "action", action: "tag"}) }
                IconButton { icon: "🗑️"; onActivated: root.send({type: "action", action: "delete"}) }
            }
        }

        // ─── Anterior / siguiente a los lados ────────────────────────────────────
        IconButton {
            anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
            size: 48; icon: "❮"; color: "#66000000"
            opacity: root.controlsShown ? 1 : 0; visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            onActivated: root.send({type: "action", action: "prev"})
        }
        IconButton {
            anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
            size: 48; icon: "❯"; color: "#66000000"
            opacity: root.controlsShown ? 1 : 0; visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            onActivated: root.send({type: "action", action: "next"})
        }

        // ─── Barra inferior ──────────────────────────────────────────────────────
        Rectangle {
            id: bottomBar
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 84
            opacity: root.controlsShown ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            gradient: Gradient {
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1; color: "#cc000000" }
            }

            // Barra de progreso: clic salta, arrastrar recorre el video.
            Item {
                id: seek
                anchors { left: parent.left; right: parent.right; leftMargin: 14; rightMargin: 14; bottom: controlsRow.top; bottomMargin: 2 }
                height: 22
                readonly property real dur: Math.max(1, player.duration)
                readonly property real shown: root.scrubbing ? root.scrubPos : player.position
                readonly property bool hot: seekArea.containsMouse || root.scrubbing

                Rectangle {
                    id: track
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    height: seek.hot ? 6 : 4; radius: height / 2
                    color: "#44ffffff"
                    Behavior on height { NumberAnimation { duration: 100 } }
                    Rectangle {
                        width: seekArea.containsMouse ? seekArea.mouseX : 0
                        height: parent.height; radius: parent.radius; color: "#33ffffff"
                    }
                    Rectangle {
                        width: parent.width * Math.min(1, seek.shown / seek.dur)
                        height: parent.height; radius: parent.radius; color: "#6c5ce7"
                    }
                }
                Rectangle {
                    width: seek.hot ? 14 : 0; height: width; radius: width / 2
                    color: "white"
                    x: track.width * Math.min(1, seek.shown / seek.dur) - width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    Behavior on width { NumberAnimation { duration: 100 } }
                }
                // Tiempo bajo el cursor
                Rectangle {
                    visible: seekArea.containsMouse || root.scrubbing
                    readonly property real at: root.scrubbing ? track.width * root.scrubPos / seek.dur : seekArea.mouseX
                    x: Math.max(0, Math.min(seek.width - width, at - width / 2))
                    y: -30
                    width: hoverTime.implicitWidth + 14; height: 22; radius: 6
                    color: "#dd000000"
                    Text {
                        id: hoverTime
                        anchors.centerIn: parent
                        color: "white"; font.pixelSize: 12
                        text: root.fmt(root.scrubbing ? root.scrubPos : seekArea.mouseX / Math.max(1, track.width) * seek.dur)
                    }
                }
                MouseArea {
                    id: seekArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    function msAt(x) { return Math.max(0, Math.min(1, x / Math.max(1, width))) * seek.dur }
                    onPressed: (m) => { root.scrubbing = true; root.scrubPos = msAt(m.x); player.position = root.scrubPos; root.poke() }
                    onPositionChanged: (m) => {
                        root.poke()
                        if (pressed) { root.scrubPos = msAt(m.x); scrubTimer.start() }
                    }
                    onReleased: (m) => { scrubTimer.stop(); root.seekTo(msAt(m.x)); root.scrubbing = false }
                    onCanceled: root.scrubbing = false
                    // Al arrastrar, busca como mucho cada 120 ms para no saturar el decodificador.
                    Timer { id: scrubTimer; interval: 120; onTriggered: player.position = root.scrubPos }
                }
            }

            Row {
                id: controlsRow
                anchors { left: parent.left; leftMargin: 8; bottom: parent.bottom; bottomMargin: 8 }
                spacing: 2
                IconButton { icon: root.playing ? "❚❚" : "▶"; onActivated: root.togglePlay() }
                IconButton { icon: "↺"; onActivated: root.seekBy(-10) }
                IconButton { icon: "↻"; onActivated: root.seekBy(10) }
                IconButton {
                    icon: audio.muted || audio.volume === 0 ? "🔇" : "🔊"
                    onActivated: audio.muted = !audio.muted
                }
                // Volumen
                Item {
                    width: 90; height: 36
                    Rectangle {
                        id: volTrack
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                        height: 4; radius: 2; color: "#44ffffff"
                        Rectangle { width: parent.width * (audio.muted ? 0 : audio.volume); height: parent.height; radius: 2; color: "white" }
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        function apply(x) { audio.volume = Math.max(0, Math.min(1, x / width)); audio.muted = false; root.poke() }
                        onPressed: (m) => apply(m.x)
                        onPositionChanged: (m) => { if (pressed) apply(m.x) }
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    leftPadding: 10
                    color: "#eeeeee"; font.pixelSize: 13
                    text: root.fmt(seek.shown) + " / " + root.fmt(player.duration)
                }
            }

            IconButton {
                // En modo cine deja libre la esquina del botón de tema de la página.
                anchors { right: parent.right; rightMargin: root.cinema ? 60 : 8; bottom: parent.bottom; bottomMargin: 8 }
                icon: root.cinema ? "🗗" : "⛶"
                onActivated: root.send({type: "action", action: "cinema"})
            }
        }
    }

    // Zonas donde la página queda encima del video (lista, avisos, cabecera del modo cine).
    // QQuickWidget ignora la máscara de QWidget al pintar, así que el recorte se hace aquí.
    Item {
        id: maskItem
        anchors.fill: parent
        visible: false
        layer.enabled: true
        Repeater {
            model: root.holes
            Rectangle { x: modelData[0]; y: modelData[1]; width: modelData[2]; height: modelData[3]; color: "white" }
        }
    }


    Keys.onPressed: (e) => {
        const k = e.key
        if (k === Qt.Key_Space || k === Qt.Key_K) togglePlay()
        else if (k === Qt.Key_Left) seekBy(-5)
        else if (k === Qt.Key_Right) seekBy(5)
        else if (k === Qt.Key_J) seekBy(-10)
        else if (k === Qt.Key_L) seekBy(10)
        else if (k === Qt.Key_Up) setVolume(audio.volume + 0.05)
        else if (k === Qt.Key_Down) setVolume(audio.volume - 0.05)
        else if (k === Qt.Key_M) audio.muted = !audio.muted
        else if (k === Qt.Key_F) send({type: "action", action: "cinema"})
        else if (k === Qt.Key_Home) seekTo(0)
        else if (k === Qt.Key_End) seekTo(player.duration)
        else if (k >= Qt.Key_0 && k <= Qt.Key_9) seekTo(player.duration * (k - Qt.Key_0) / 10)
        else if (k === Qt.Key_N) send({type: "action", action: "next"})
        else if (k === Qt.Key_P) send({type: "action", action: "prev"})
        else if (k === Qt.Key_Escape) send({type: "action", action: "escape"})
        else return
        e.accepted = true
        poke()
    }
}
