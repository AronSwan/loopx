use command_group::{CommandGroup, GroupChild};
use std::{
    env, fmt,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

const STARTUP_TIMEOUT: Duration = Duration::from_secs(15);
const PROBE_TIMEOUT: Duration = Duration::from_millis(500);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ServiceKind {
    Status,
    Chat,
}

impl ServiceKind {
    fn label(self) -> &'static str {
        match self {
            Self::Status => "status",
            Self::Chat => "chat",
        }
    }

    fn port(self) -> u16 {
        match self {
            Self::Status => 8766,
            Self::Chat => 8767,
        }
    }

    fn probe_path(self) -> &'static str {
        match self {
            Self::Status => "/",
            Self::Chat => "/api/chat/capabilities",
        }
    }

    fn expected_marker(self) -> &'static str {
        match self {
            Self::Status => "\"source\":\"serve-status\"",
            Self::Chat => "\"schema_version\":\"loopx_chat_capabilities_v1\"",
        }
    }

    fn command_args(self) -> Vec<String> {
        match self {
            Self::Status => vec![
                "serve-status",
                "--global-registry",
                "--host",
                "127.0.0.1",
                "--port",
                "8766",
                "--limit",
                "80",
            ],
            Self::Chat => vec![
                "chat",
                "--global-registry",
                "--host",
                "127.0.0.1",
                "--port",
                "8767",
                "--no-open",
            ],
        }
        .into_iter()
        .map(str::to_string)
        .collect()
    }
}

#[derive(Debug, Eq, PartialEq)]
enum Probe {
    Matching,
    Unavailable,
    Foreign,
}

#[derive(Debug)]
pub struct ServiceError(String);

impl fmt::Display for ServiceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for ServiceError {}

struct OwnedService {
    child: GroupChild,
}

impl OwnedService {
    fn stop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub struct ServiceSet {
    owned: Vec<OwnedService>,
}

impl ServiceSet {
    pub fn start() -> Result<Self, ServiceError> {
        let mut services = Self { owned: Vec::new() };
        for kind in [ServiceKind::Status, ServiceKind::Chat] {
            if let Err(error) = services.ensure(kind) {
                services.stop();
                return Err(error);
            }
        }
        Ok(services)
    }

    fn ensure(&mut self, kind: ServiceKind) -> Result<(), ServiceError> {
        match probe(kind) {
            Probe::Matching => return Ok(()),
            Probe::Foreign => {
                return Err(ServiceError(format!(
                    "port {} is occupied by a service that is not LoopX {}",
                    kind.port(),
                    kind.label()
                )));
            }
            Probe::Unavailable => {}
        }

        let executable = loopx_executable();
        let mut command = Command::new(&executable);
        command
            .args(kind.command_args())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let child = command.group_spawn().map_err(|error| {
            ServiceError(format!(
                "could not start LoopX {} with `{executable}`: {error}",
                kind.label()
            ))
        })?;
        self.owned.push(OwnedService { child });

        let deadline = Instant::now() + STARTUP_TIMEOUT;
        while Instant::now() < deadline {
            match probe(kind) {
                Probe::Matching => return Ok(()),
                Probe::Foreign => {
                    return Err(ServiceError(format!(
                        "LoopX {} startup reached an unexpected service on port {}",
                        kind.label(),
                        kind.port()
                    )));
                }
                Probe::Unavailable => thread::sleep(Duration::from_millis(100)),
            }
        }
        Err(ServiceError(format!(
            "LoopX {} did not become ready on port {}",
            kind.label(),
            kind.port()
        )))
    }

    pub fn stop(&mut self) {
        for service in self.owned.iter_mut().rev() {
            service.stop();
        }
        self.owned.clear();
    }
}

impl Drop for ServiceSet {
    fn drop(&mut self) {
        self.stop();
    }
}

fn loopx_executable() -> String {
    if let Ok(configured) = env::var("LOOPX_BIN") {
        if !configured.trim().is_empty() {
            return configured;
        }
    }
    let mut candidates = vec![
        PathBuf::from("/usr/local/bin/loopx"),
        PathBuf::from("/opt/homebrew/bin/loopx"),
    ];
    if let Some(home) = env::var_os("HOME") {
        candidates.insert(0, PathBuf::from(home).join(".local/bin/loopx"));
    }
    candidates
        .into_iter()
        .find(|candidate| candidate.is_file())
        .map(|candidate| candidate.to_string_lossy().into_owned())
        .unwrap_or_else(|| "loopx".to_string())
}

fn probe(kind: ServiceKind) -> Probe {
    let address = SocketAddr::from(([127, 0, 0, 1], kind.port()));
    let mut stream = match TcpStream::connect_timeout(&address, PROBE_TIMEOUT) {
        Ok(stream) => stream,
        Err(_) => return Probe::Unavailable,
    };
    let _ = stream.set_read_timeout(Some(PROBE_TIMEOUT));
    let _ = stream.set_write_timeout(Some(PROBE_TIMEOUT));
    let request = format!(
        "GET {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
        kind.probe_path(),
        kind.port()
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return Probe::Foreign;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return Probe::Foreign;
    }
    classify_response(kind, &response)
}

fn classify_response(kind: ServiceKind, response: &str) -> Probe {
    let compact: String = response
        .chars()
        .filter(|character| !character.is_ascii_whitespace())
        .collect();
    if response.starts_with("HTTP/1.")
        && response.contains(" 200 ")
        && compact.contains(kind.expected_marker())
    {
        Probe::Matching
    } else {
        Probe::Foreign
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn service_commands_stay_loopback_and_global() {
        let status = ServiceKind::Status.command_args();
        let chat = ServiceKind::Chat.command_args();

        assert!(status
            .windows(2)
            .any(|pair| pair == ["--host", "127.0.0.1"]));
        assert!(chat.windows(2).any(|pair| pair == ["--host", "127.0.0.1"]));
        assert!(status
            .iter()
            .any(|argument| argument == "--global-registry"));
        assert!(chat.iter().any(|argument| argument == "--global-registry"));
        assert!(chat.iter().any(|argument| argument == "--no-open"));
    }

    #[test]
    fn configured_loopx_binary_takes_precedence() {
        std::env::set_var("LOOPX_BIN", "/fixture/loopx");
        assert_eq!(loopx_executable(), "/fixture/loopx");
        std::env::remove_var("LOOPX_BIN");
    }

    #[test]
    fn service_fingerprints_reject_unknown_responses() {
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.1 200 OK\r\n\r\n{\"source\":\"other\"}"
            ),
            Probe::Foreign
        );
        assert_eq!(
            classify_response(
                ServiceKind::Chat,
                "HTTP/1.1 200 OK\r\n\r\n{\"schema_version\":\"other\"}"
            ),
            Probe::Foreign
        );
    }

    #[test]
    fn service_fingerprints_accept_only_expected_loopx_payloads() {
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.1 200 OK\r\n\r\n{\"source\": \"serve-status\"}"
            ),
            Probe::Matching
        );
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.0 200 OK\r\n\r\n{\n  \"source\": \"serve-status\"\n}"
            ),
            Probe::Matching
        );
        assert_eq!(
            classify_response(
                ServiceKind::Chat,
                "HTTP/1.1 200 OK\r\n\r\n{\"schema_version\":\"loopx_chat_capabilities_v1\"}"
            ),
            Probe::Matching
        );
    }
}
