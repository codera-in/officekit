use super::invoice_library_reconnect;
use crate::workspace_native::NativeGrantToken;
use crate::{BackendApiAddress, BackendApiToken};
use std::io::{Read, Write};
use std::net::TcpListener;
use tauri::Manager;

const ID: &str = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";

fn run(response: &str, id: &str) -> (Result<serde_json::Value, String>, String) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let response = response.to_owned();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = vec![0; 8192];
        let size = stream.read(&mut request).unwrap();
        let request = String::from_utf8(request[..size].to_vec()).unwrap();
        stream.write_all(response.as_bytes()).unwrap();
        request
    });
    let app = tauri::test::mock_app();
    app.manage(NativeGrantToken("test-native".into()));
    app.manage(BackendApiToken("test-api".into()));
    app.manage(BackendApiAddress(address));
    let result = invoice_library_reconnect(id.into(), app.state(), app.state(), app.state());
    (result, server.join().unwrap())
}

#[test]
fn reconnect_uses_fixed_route_and_hidden_credentials() {
    let (result, request) = run("HTTP/1.1 200 OK\r\nContent-Length: 18\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ready\"}", ID);
    assert_eq!(result.unwrap(), serde_json::json!({"status":"ready"}));
    assert!(request.starts_with(&format!(
        "POST /api/invoice-libraries/{ID}/reconnections HTTP/1.1"
    )));
    let lower = request.to_lowercase();
    assert!(lower.contains("authorization: bearer test-api"));
    assert!(lower.contains("x-officekit-native-grant: test-native"));
}

#[test]
fn reconnect_refuses_invalid_and_injected_ids_before_network_access() {
    let app = tauri::test::mock_app();
    app.manage(NativeGrantToken("test-native".into()));
    app.manage(BackendApiToken("test-api".into()));
    app.manage(BackendApiAddress("127.0.0.1:1".parse().unwrap()));
    for id in [
        "",
        "../file-selections",
        "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE",
        "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee/reconnections",
    ] {
        let result = invoice_library_reconnect(id.into(), app.state(), app.state(), app.state());
        assert_eq!(result.unwrap_err(), "Choose a valid invoice library.");
    }
}

#[test]
fn reconnect_maps_transport_status_and_invalid_response_to_safe_errors() {
    let (result, _) = run("HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n", ID);
    assert_eq!(
        result.unwrap_err(),
        "The invoice folder could not be reconnected. Choose the folder again."
    );
    let (result, _) = run("HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nno!", ID);
    assert_eq!(
        result.unwrap_err(),
        "The invoice folder returned invalid metadata."
    );
    let (result, _) = run("HTTP/1.1 200 OK\r\nContent-Length: 2000000\r\n\r\n{}", ID);
    assert_eq!(
        result.unwrap_err(),
        "The invoice folder returned invalid metadata."
    );
}
