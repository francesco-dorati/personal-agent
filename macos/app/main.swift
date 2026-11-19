// Personal Agent.app: a small native window around the Personal Agent TUI.
//
// It starts the bundled server script (Resources/server.sh), waits for the
// "READY <url>" line, and shows that page in a WKWebView. The page ships its
// own fonts, so the icons always render. When the TUI quits (Q), the page tells
// us and the app closes. Built by macos/make-app.sh with swiftc.

import Cocoa
import WebKit

let background = NSColor(srgbRed: 0x26 / 255.0, green: 0x26 / 255.0, blue: 0x24 / 255.0, alpha: 1)

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var server: Process?
    var pageURL: URL?
    var retries = 0
    let logURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Logs/PersonalAgent.log")

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()

        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "personalAgent")
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        if #available(macOS 12.0, *) { webView.underPageBackgroundColor = background }

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "Personal Agent"
        window.titlebarAppearsTransparent = true
        window.backgroundColor = background
        window.appearance = NSAppearance(named: .darkAqua)
        window.minSize = NSSize(width: 900, height: 600)
        window.contentView = webView
        window.center()
        window.setFrameAutosaveName("PersonalAgentMain")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        showMessage("Starting…")
        startServer()
    }

    // MARK: server

    func startServer() {
        guard let script = Bundle.main.url(forResource: "server", withExtension: "sh") else {
            return showMessage("Missing server.sh. Re-run macos/make-app.sh.")
        }
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let log = try? FileHandle(forWritingTo: logURL)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = [script.path]
        var env = ProcessInfo.processInfo.environment
        env["PA_APP_CHILD"] = "1"
        process.environment = env

        let out = Pipe()
        process.standardOutput = out
        process.standardError = log
        out.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            for line in text.split(separator: "\n") where line.hasPrefix("READY ") {
                let url = URL(string: line.dropFirst(6).trimmingCharacters(in: .whitespaces))
                DispatchQueue.main.async {
                    guard let self = self, self.pageURL == nil, let url = url else { return }
                    self.pageURL = url
                    self.loadPage()
                }
            }
        }
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self, self.pageURL == nil else { return }
                self.showMessage("Couldn't start. Details in ~/Library/Logs/PersonalAgent.log")
            }
        }
        do {
            try process.run()
            server = process
        } catch {
            showMessage("Couldn't start: \(error.localizedDescription)")
        }
    }

    func loadPage() {
        guard let url = pageURL else { return }
        webView.load(URLRequest(url: url))
    }

    // The server prints READY just before it listens: retry briefly.
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        guard pageURL != nil else { return }
        if retries < 80 {
            retries += 1
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { self.loadPage() }
        } else {
            showMessage("Couldn't connect. Details in ~/Library/Logs/PersonalAgent.log")
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        window.makeFirstResponder(webView)
    }

    // The page posts "closed" when the TUI quits.
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        if (message.body as? String) == "closed" { NSApp.terminate(nil) }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        server?.terminate()
    }

    func showMessage(_ text: String) {
        let html = """
        <html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
        background:#262624;color:#a9a49c;font:15px Menlo,monospace">\(text)</body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    // MARK: menu

    func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Personal Agent", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Personal Agent", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Personal Agent", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        main.addItem(editItem)

        let windowItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowItem.submenu = windowMenu
        main.addItem(windowItem)

        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
