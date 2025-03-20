<?php
//$host="northeastdyn0721.ddns.net";
$host="127.0.0.1";
$user="test";
$pw="ThisONE@";
$db="LemonKricket";

$conn = mysqli_connect($host, $user, $pw, $db);

//echo $_POST['nav'];

if($_POST['nav']==1) {

  $file_data=file_get_contents($_FILES['file']);
  $file_info=finfo_open(FILEINFO_MIME_TYPE);
  $file_type=finfo_file($file_info, $_FILES['file']);
  $file_size=filesize($_FILES['file']);


  $sql="update tbinventory set imagefile='".mysqli_real_escape_string($file_data) . "', imagefile_type='" .$file_type ."' where inventoryID=" . $_POST['record'];
echo $sql;

  msqli_query($conn,$sql);

} else {

  require("upload.inc");

}



?>
