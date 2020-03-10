import requests
import socket
from pg_controller.workers import looping_thread
import logging
from abc import ABC, abstractmethod


class ElectionStatusHandler(ABC):

    @abstractmethod
    def handle_status(self, is_leader):
        pass


class Election(looping_thread.LoopingThread):

    CONSUL_BASE_URL = "http://localhost:8500/v1"
    CONSUL_SESSION_URL = CONSUL_BASE_URL + "/session/{}"
    CONSUL_KV_URL = CONSUL_BASE_URL + "/kv/{}"

    def __init__(self, election_consul_key, consul_session_checks, election_status_handler, host_ip, time_step_seconds):
        super().__init__()
        self._election_consul_key = election_consul_key
        self._consul_session_checks = consul_session_checks
        self._election_status_handler = election_status_handler
        self._host_ip = host_ip
        self._time_step_seconds = time_step_seconds
        self._create_consul_session()

    def _create_consul_session(self):
        logging.info("Creating Consul session for leader election")
        response = requests.put(self.__class__.CONSUL_SESSION_URL.format("create"),
                                json={"Checks": self._consul_session_checks})

        logging.info("Response (%d) %s", response.status_code, response.text)
        response.raise_for_status()
        
        self._session_id = response.json()["ID"]

    def _acquire_lock(self):
        logging.info("Attempting to acquire lock over election key")
        response = requests.put(self.__class__.CONSUL_KV_URL.format(self._election_consul_key),
                                params={"acquire": self._session_id},
                                json={
                                    "host": self._host_ip,
                                    "node": socket.gethostname()
                                })

        logging.info("Response (%d) %s", response.status_code, response.text)
        if response.status_code == 500 and "invalid session" in response.text:
            self._create_consul_session()
        else:
            response.raise_for_status()

        return response.text == "true"

    def do_one_run(self):
        try:
            is_leader = self._acquire_lock()
            continue_trying = self._election_status_handler.handle_status(is_leader)
            if continue_trying is False:
                logging.info("Status handler decided to stop the election loop!")
                self.stop()
        except:
            logging.exception("An error occurred during leader election!")

        self.wait(self._time_step_seconds)
