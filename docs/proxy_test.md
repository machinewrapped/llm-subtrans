# Testing Proxy Support

This guide explains how to test the proxy support feature in llm-subtrans using a real proxy server and actual translation workloads.

## Prerequisites

You need a proxy server to test with. The easiest option is to use `mitmproxy`, which can be installed into the project's virtual environment.

## Installation

Install mitmproxy in the virtual environment:

```bash
# Windows
.\envsubtrans\Scripts\python.exe -m pip install mitmproxy

# Linux/Mac
./envsubtrans/bin/python -m pip install mitmproxy
```

## Testing Procedure

### Step 1: Start the Proxy Server

Open a terminal and start `mitmdump` (the non-interactive version of mitmproxy):

```bash
# Windows
.\envsubtrans\Scripts\mitmdump.exe --listen-port 8888 --ssl-insecure

# Linux/Mac
./envsubtrans/bin/mitmdump --listen-port 8888 --ssl-insecure
```

This starts a proxy server on port 8888 that will:
- Log all HTTP/HTTPS traffic passing through it
- Allow you to verify that your translation requests are using the proxy
- Show the actual API endpoints being called

**Keep this terminal open** - you'll see traffic logs here when requests go through the proxy.

### Step 2: Run a Translation with Proxy

In a **second terminal**, run your translation through the helper script to ensure the certificate is trusted:

```bash
.\scripts\run-with-proxy.bat llm-subtrans.cmd test.srt -l English --proxy http://127.0.0.1:8888 --maxlines 10
```

This helper script sets the `SSL_CERT_FILE` environment variable for the duration of the command.

### Step 3: Verify Proxy Usage

**In Terminal 1 (mitmdump)**, you should see HTTP/HTTPS requests being logged, such as:

- For Gemini: Requests to `generativelanguage.googleapis.com`
- For Mistral: Requests to `api.mistral.ai`
- For Custom: Requests to your specified server
- For DeepSeek: Requests to `api.deepseek.com`

**Example output from mitmdump:**
```
127.0.0.1:54321 CONNECT generativelanguage.googleapis.com:443
127.0.0.1:54321 POST https://generativelanguage.googleapis.com/v1alpha/models/gemini-2.0-flash:generateContent
```

**In Terminal 2**, you should see:
- Normal translation progress
- Debug logs (if `--debug` is enabled)
- No errors related to proxy configuration

## What to Expect

### Successful Proxy Test

✅ **Terminal 1 shows traffic**: You see CONNECT and POST/GET requests to API endpoints
✅ **Terminal 2 shows progress**: Translation proceeds normally
✅ **No proxy errors**: No connection errors or proxy-related failures

### Failed Proxy Test

❌ **Terminal 1 shows nothing**: No traffic indicates the proxy isn't being used
❌ **Terminal 2 shows errors**: Connection failures or timeout errors
❌ **Requests bypass proxy**: Check your proxy URL format

## Proxy URL Format

The `--proxy` argument accepts standard proxy URLs:

- HTTP proxy: `http://127.0.0.1:8888`
- HTTPS proxy: `https://127.0.0.1:8888`
- SOCKS5 proxy: `socks5://127.0.0.1:1080`

## Troubleshooting

### No Traffic in mitmdump

**Problem**: Terminal 1 shows no requests, but translation is working.

**Possible causes**:
1. Proxy argument not being passed correctly
2. Provider doesn't support proxy configuration
3. Proxy URL format is incorrect

**Solution**: Check that:
- The `--proxy` argument is spelled correctly
- The proxy URL uses the correct format
- Add `--debug` to see detailed logs

### Connection Timeout Errors

**Problem**: Translation fails with timeout or connection errors.

**Possible causes**:
1. mitmdump isn't running
2. Wrong port number
3. Firewall blocking connections

**Solution**:
- Verify mitmdump is running on the expected port
- Check firewall settings
- Try a different port number

### SSL/TLS Certificate Errors

**Problem**: Errors about certificate verification (e.g., `unknown ca` or `Client TLS handshake failed`).

**Explanation**: When `mitmproxy` intercepts HTTPS traffic, it presents its own certificate. Your Python environment doesn't trust this certificate by default.

**Solution A: Use the --proxycert Argument (Recommended)**
You can pass the path to your mitmproxy CA certificate directly to the translation script:
```bash
# Windows
.\llm-subtrans.cmd test.srt -l English --proxy http://127.0.0.1:8888 --proxycert %USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem
```
This automatically sets up the environment to trust the proxy's certificate.

**Solution B: Trust the mitmproxy CA via Environment Variable**
1. Find your `mitmproxy-ca-cert.pem` file (usually in `%USERPROFILE%\.mitmproxy\`).
2. Set the `SSL_CERT_FILE` environment variable in your terminal before running the app:
   ```powershell
   # Windows PowerShell
   $env:SSL_CERT_FILE = "$HOME\.mitmproxy\mitmproxy-ca-cert.pem"
   ```
3. Run the translation again. The libraries (`httpx`, `aiohttp`, etc.) will now trust the proxy.

**Solution B: Simple Connectivity Testing (No decryption)**
If you only want to verify that the app *reaches* the proxy and don't need to see the JSON contents, run `mitmdump` with the `--ignore-hosts` flag:
```bash
mitmdump --listen-port 8888 --ignore-hosts '.*'
```
This tells `mitmproxy` to act as a simple TCP tunnel. It won't intercept the SSL, so the client will trust the real server's certificate, but `mitmdump` will only show the `CONNECT` request, not the actual API data.

## Testing with Real Proxies

While mitmproxy is great for testing, you can also test with:

1. **Corporate proxies**: If you're behind a corporate proxy
2. **SOCKS proxies**: For routing traffic through SSH tunnels
3. **VPN software**: Some VPN clients provide local proxy endpoints

Simply replace `http://127.0.0.1:8888` with your actual proxy URL.

## Supported Providers

The following providers support the `--proxy` argument:

- ✅ OpenAI (`gpt-subtrans.py`)
- ✅ Claude (`claude-subtrans.py`)
- ✅ Gemini (`gemini-subtrans.py`)
- ✅ Mistral (`mistral-subtrans.py`)
- ✅ OpenRouter (`llm-subtrans.py`)
- ✅ DeepSeek (`deepseek-subtrans.py`)
