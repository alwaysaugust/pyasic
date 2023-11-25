# ------------------------------------------------------------------------------
#  Copyright 2022 Upstream Data Inc                                            -
#                                                                              -
#  Licensed under the Apache License, Version 2.0 (the "License");             -
#  you may not use this file except in compliance with the License.            -
#  You may obtain a copy of the License at                                     -
#                                                                              -
#      http://www.apache.org/licenses/LICENSE-2.0                              -
#                                                                              -
#  Unless required by applicable law or agreed to in writing, software         -
#  distributed under the License is distributed on an "AS IS" BASIS,           -
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.    -
#  See the License for the specific language governing permissions and         -
#  limitations under the License.                                              -
# ------------------------------------------------------------------------------

import asyncio
import ipaddress
import logging
from typing import AsyncIterator, List, Union

from pyasic import settings
from pyasic.miners.miner_factory import AnyMiner, miner_factory


class MinerNetwork:
    """A class to handle a network containing miners. Handles scanning and gets miners via [`MinerFactory`][pyasic.miners.miner_factory.MinerFactory].

    Parameters:
        hosts: A list of `ipaddress.IPv4Address` to be used when scanning.
    """

    def __init__(self, hosts: List[ipaddress.IPv4Address]):
        self.hosts = hosts

    def __len__(self):
        return len(self.hosts)

    @classmethod
    def from_list(cls, addresses: list):
        """Parse a list of address constructors into a MinerNetwork.

        Parameters:
            addresses: A list of address constructors, such as `["10.1-2.1.1-50", "10.4.1-2.1-50"]`.
        """
        hosts = []
        for address in addresses:
            hosts = [*hosts, *cls.from_address(address)]
        return sorted(list(set(hosts)))

    @classmethod
    def from_address(cls, address: str):
        """Parse an address constructor into a MinerNetwork.

        Parameters:
            address: An address constructor, such as `"10.1-2.1.1-50"`.
        """
        octets = address.split(".")
        if len(octets) > 4:
            raise ValueError("Too many octets in IP constructor.")
        if len(octets) < 4:
            raise ValueError("Too few octets in IP constructor.")
        return cls.from_octets(*octets)

    @classmethod
    def from_octets(cls, oct_1: str, oct_2: str, oct_3: str, oct_4: str):
        """Parse 4 octet constructors into a MinerNetwork.

        Parameters:
            oct_1: An octet constructor, such as `"10"`.
            oct_2: An octet constructor, such as `"1-2"`.
            oct_3: An octet constructor, such as `"1"`.
            oct_4: An octet constructor, such as `"1-50"`.
        """

        hosts = []

        oct_1_val_start, oct_1_start, oct_1_end = compute_oct_range(oct_1)
        for oct_1_idx in range((abs(oct_1_end - oct_1_start)) + 1):
            oct_1_val = str(oct_1_idx + oct_1_start)

            oct_2_val_start, oct_2_start, oct_2_end = compute_oct_range(oct_2)
            for oct_2_idx in range((abs(oct_2_end - oct_2_start)) + 1):
                oct_2_val = str(oct_2_idx + oct_2_start)

                oct_3_val_start, oct_3_start, oct_3_end = compute_oct_range(oct_3)
                for oct_3_idx in range((abs(oct_3_end - oct_3_start)) + 1):
                    oct_3_val = str(oct_3_idx + oct_3_start)

                    oct_4_val_start, oct_4_start, oct_4_end = compute_oct_range(oct_4)
                    for oct_4_idx in range((abs(oct_4_end - oct_4_start)) + 1):
                        oct_4_val = str(oct_4_idx + oct_4_start)

                        hosts.append(
                            ipaddress.ip_address(
                                ".".join([oct_1_val, oct_2_val, oct_3_val, oct_4_val])
                            )
                        )
        return sorted(hosts)

    @classmethod
    def from_subnet(cls, subnet: str):
        """Parse a subnet into a MinerNetwork.

        Parameters:
            subnet: A subnet string, such as `"10.0.0.1/24"`.
        """
        return list(ipaddress.ip_network(subnet, strict=False).hosts())

    async def scan_network_for_miners(self) -> List[AnyMiner]:
        """Scan the network for miners, and return found miners as a list.

        Returns:
            A list of found miners.
        """
        logging.debug(f"{self} - (Scan Network For Miners) - Scanning")

        # clear cached miners
        miner_factory.clear_cached_miners()

        limit = asyncio.Semaphore(settings.get("network_scan_threads", 300))
        miners = await asyncio.gather(
            *[self.ping_and_get_miner(host, limit) for host in self.hosts]
        )

        # remove all None from the miner list
        miners = list(filter(None, miners))
        logging.debug(
            f"{self} - (Scan Network For Miners) - Found {len(miners)} miners"
        )

        # return the miner objects
        return miners

    async def scan_network_generator(self) -> AsyncIterator[AnyMiner]:
        """
        Scan the network for miners using an async generator.

        Returns:
             An asynchronous generator containing found miners.
        """
        # get the current event loop
        loop = asyncio.get_event_loop()

        # create a list of scan tasks
        limit = asyncio.Semaphore(settings.get("network_scan_threads", 300))
        miners = asyncio.as_completed(
            [
                loop.create_task(self.ping_and_get_miner(host, limit))
                for host in self.hosts
            ]
        )
        for miner in miners:
            try:
                yield await miner
            except TimeoutError:
                yield None

    @staticmethod
    async def ping_miner(
        ip: ipaddress.ip_address, semaphore: asyncio.Semaphore
    ) -> Union[None, ipaddress.ip_address]:
        async with semaphore:
            try:
                miner = await ping_miner(ip)
                if miner:
                    return miner
            except ConnectionRefusedError:
                tasks = [ping_miner(ip, port=port) for port in [4029, 8889]]
                for miner in asyncio.as_completed(tasks):
                    try:
                        miner = await miner
                        if miner:
                            return miner
                    except ConnectionRefusedError:
                        pass

    @staticmethod
    async def ping_and_get_miner(
        ip: ipaddress.ip_address, semaphore: asyncio.Semaphore
    ) -> Union[None, AnyMiner]:
        async with semaphore:
            try:
                miner = await ping_and_get_miner(ip)
                if miner:
                    return miner
            except ConnectionRefusedError:
                tasks = [ping_and_get_miner(ip, port=port) for port in [4029, 8889]]
                for miner in asyncio.as_completed(tasks):
                    try:
                        miner = await miner
                        if miner:
                            return miner
                    except ConnectionRefusedError:
                        pass


async def ping_miner(
    ip: ipaddress.ip_address, port=4028
) -> Union[None, ipaddress.ip_address]:
    for i in range(settings.get("network_ping_retries", 1)):
        try:
            connection_fut = asyncio.open_connection(str(ip), port)
            # get the read and write streams from the connection
            reader, writer = await asyncio.wait_for(
                connection_fut, timeout=settings.get("network_ping_timeout", 3)
            )
            # immediately close connection, we know connection happened
            writer.close()
            # make sure the writer is closed
            await writer.wait_closed()
            # ping was successful
            return ip
        except asyncio.exceptions.TimeoutError:
            # ping failed if we time out
            continue
        except (ConnectionRefusedError, OSError):
            # handle for other connection errors
            logging.debug(f"{str(ip)}: Connection Refused.")
            raise ConnectionRefusedError
        except Exception as e:
            logging.warning(f"{str(ip)}: Ping And Get Miner Exception: {e}")
            raise ConnectionRefusedError
    return


async def ping_and_get_miner(
    ip: ipaddress.ip_address, port=4028
) -> Union[None, AnyMiner]:
    for i in range(settings.get("network_ping_retries", 1)):
        try:
            connection_fut = asyncio.open_connection(str(ip), port)
            # get the read and write streams from the connection
            reader, writer = await asyncio.wait_for(
                connection_fut, timeout=settings.get("network_ping_timeout", 3)
            )
            # immediately close connection, we know connection happened
            writer.close()
            # make sure the writer is closed
            await writer.wait_closed()
            # ping was successful
            return await miner_factory.get_miner(ip)
        except asyncio.exceptions.TimeoutError:
            # ping failed if we time out
            continue
        except (ConnectionRefusedError, OSError):
            # handle for other connection errors
            logging.debug(f"{str(ip)}: Connection Refused.")
            raise ConnectionRefusedError
        except Exception as e:
            logging.warning(f"{str(ip)}: Ping And Get Miner Exception: {e}")
            raise ConnectionRefusedError
    return


def compute_oct_range(octet: str) -> tuple:
    octet_split = octet.split("-")
    octet_start = int(octet_split[0])
    octet_end = None
    try:
        octet_end = int(octet_split[1])
    except IndexError:
        pass
    if octet_end is None:
        octet_end = int(octet_start)

    octet_val_start = min([octet_start, octet_end])

    return octet_val_start, octet_start, octet_end
