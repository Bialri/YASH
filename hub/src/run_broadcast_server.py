from registration.servers import BroadcastServer
import multiprocessing
import time
import datetime


def main():
    start = datetime.datetime.now()
    udp_server = BroadcastServer(15555, 12222)
    process = multiprocessing.Process(target=udp_server.run_server)
    try:
        process.start()

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        udp_server.stop()
        print(datetime.datetime.now() - start)
        process.join()

if __name__ == '__main__':
    main()
