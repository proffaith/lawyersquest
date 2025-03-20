<?php
include("index.html");

print("This is a php page running on the new site and apache install.");

$pythonScript = '/Users/timfaith/Downloads/SERA.py';
$command = 'python3.11 ' . $pythonScript;
$output = exec($command);
echo $output;

$pythonScript = '/Users/timfaith/Downloads/SERAUSDC.py';
$command = 'python3.11 ' . $pythonScript;
$output = exec($command);
echo $output;

?>
