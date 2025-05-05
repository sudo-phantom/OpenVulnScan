# scanners/nmap_runner.py
import subprocess
import re
import ipaddress
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Union, Optional


class NmapRunner:
    def __init__(self, targets: List[str]):
        """
        Initialize the NmapRunner with a list of target IPs or hostnames
        
        Args:
            targets: List of IP addresses, hostnames, or CIDR notations to scan
        """
        self.targets = targets
        
    def run(self, options: Optional[List[str]] = None) -> List[str]:
        """
        Run an Nmap scan on the specified targets with optional parameters
        
        Args:
            options: Additional Nmap options as a list of strings
            
        Returns:
            List of findings from the scan
        """
        if not self.targets:
            return ["No targets specified"]
            
        # Convert list of targets to comma-separated string
        target_str = ','.join(self.targets)
        
        # Build the nmap command with XML output for easier parsing
        cmd = ["nmap", "-oX", "-"]  # Output XML to stdout
        
        # Add user specified options if provided
        if options:
            cmd.extend(options)
        else:
            # Default options if none specified
            cmd.extend(["-sV", "--script=vulners","--top-ports","100","-T4","-A","-R"])  # Version detection and vulnerability scanning
            
        # Add targets
        cmd.append(target_str)
        
        try:
            # Execute nmap and capture output
            
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                return [f"Nmap scan failed: {stderr}"]
                
            # Parse the output to get findings
            return self._parse_nmap_output(stdout)
            
        except FileNotFoundError:
            return ["Error: Nmap not found. Please ensure Nmap is installed and in your PATH."]
        except Exception as e:
            return [f"Error executing Nmap scan: {str(e)}"]
    
    def _parse_nmap_output(self, output: str) -> List[Dict[str, Any]]:
        results = []

        try:
            root = ET.fromstring(output)
            if root.tag != 'nmaprun':
                return []

            for host in root.findall('./host'):
                status = host.find('./status')
                if status is None or status.get('state') != 'up':
                    continue

                addr = host.find('./address').get('addr', 'unknown')
                hostname_elem = host.find('./hostnames/hostname')
                hostname = hostname_elem.get('name') if hostname_elem is not None else ""

                open_ports = []
                for port in host.findall('./ports/port'):
                    if port.find('./state').get('state') == 'open':
                        open_ports.append({
                            "port": port.get("portid"),
                            "protocol": port.get("protocol"),
                            "service": port.find('./service').get('name', 'unknown')
                        })

                vulnerabilities = []
                for script in host.findall('.//script'):
                    script_id = script.get('id', '')
                    output = script.get('output', '').strip()
                    if script_id == 'vulners' and output:
                        # Try to extract CVEs from the output
                        cves = re.findall(r'CVE-\d{4}-\d{4,7}', output)
                        for cve in cves:
                            vulnerabilities.append({
                                "id": cve,
                                "description": f"Detected by vulners script: {cve}"
                            })


                results.append({
                    "ip": addr,
                    "hostname": hostname,
                    "open_ports": open_ports,
                    "vulnerabilities": vulnerabilities
                })

            return results

        except ET.ParseError:
            return []
