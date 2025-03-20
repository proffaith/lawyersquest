<?php
//$host="northeastdyn0721.ddns.net";
$host="127.0.0.1";
$user="test";
$pw="ThisONE@";
$db="LemonKricket";

if($conn = mysqli_connect($host, $user, $pw, $db)) {

  echo "Connected successfully.";
} else {

  echo "Whoops.";
}
?>
