<?php

$host="northeastdyn0721.ddns.net";
$user="SLADMIN";
$pw="44B#pacific";
$db="AMFORTEMUSIC";

$mysqli = new mysqli($host, $user, $pw, $db);

if ($mysqli->connect_errno) {
    echo "Failed to connect to MySQL: (" . $mysqli->connect_errno . ") " . $mysqli->connect_error;
}

$cm=$_GET['command'];

Switch($cm) {

Case "add"://add new visitors and visit data transactions here

$UUID=$_GET['UUID'];
$DN=$_GET['displayname'];
$REG=$_GET['Region'];
$D=$_GET['distance'];

$result = $mysqli->query("Select id from visitors where UUID='" . $UUID . "'");

//Add to visitors table if not already there, otherwise just update the displayname with what we currently received
If(mysqli_num_rows($result) == 0) {
	$sql="insert into visitors (UUID, displayname) values ('" . $UUID . "','" . $DN . "')";
	$mysqli->query($sql);
}
else {

  $sql="update visitors set displayname='" . $DN ."', dateUpdated=now() where UUID='" . $UUID ."'";
  $mysqli->query($sql);

}

//next, add an entry to visits for the visitor_id
$resultA = $mysqli->query("Select id from visitors where UUID='" . $UUID . "'");

$visitdate=$mysqli->query("select date_format(now(),'%Y-%m-%d') as startdate");
$visitstart=$mysqli->query("select date_format(now(),'%T') as begintime");

while ($row=$resultA->fetch_row()) {

  	$rowd=$visitdate->fetch_row();
  	$rowS=$visitstart->fetch_row();

    //test to see if this visit transactions exists for today with a null endTime
    //if it does, do not insert a new row. if it does not, insert the new visit transaction
    $sql="select id from visits where visitdate=curdate() and endtime is null and visitor_id=" . $row[0] . " and Region='". $REG ."';";
    $test=$mysqli->query($sql);

    If(mysqli_num_rows($test) == 0) {
       echo "No visit records in that query." . $sql;
  	   $sql="insert into visits (visitor_id, visitdate, starttime, Region, still_here, distance) values (" . $row[0] . ",'" . $rowd[0] . "','" . $rowS[0] . "','" . $REG . "',1," . $D .");";
       $mysqli->query($sql);
        echo $sql;
     }

  }


break;

case "RUHere":

$sql="update visits set still_here = 0 where endTime is null and visitDate=curdate();";
$mysqli->query($sql);

break;


case "leave":
//look up the visitor from $UUID
//update visits for the null endtime for that visitorid
$UUID=$_GET['UUID'];
$REG=$_GET['Region'];
$D=$_GET['distance'];

$sql="select id from visitors where UUID='" . $UUID ."';";
$resultL=$mysqli->query($sql);

while($rowL=$resultL->fetch_row()) {
  $sql="update visits set still_here=1, distance=" . $D . " where visitor_id=" . $rowL[0] . " and endtime is null and Region='" . $REG . "';";
  echo $sql;
  $mysqli->query($sql);
}

break;

case "left":

$sql="update visits set endTime=date_format(now(),'%T') where endTime is null and still_here=0; ";
$mysqli->query($sql);


break;


default:


break;

}

//do garbage collection on null endtimes to update to the start of the next hour
//where starttimes are at least several hours earlier than when this is called
$sql="select * from visits where endtime is null and starttime <= date_add(now(),interval -4 hour);";
$resultB = $mysqli->query($sql);

while ($row=$resultB->fetch_row()) {

  $sql="select date_format('" . $row[2] . " " .$row[3]. "','%H')+1;";
  echo $sql;

  $endtime=$mysqli->query($sql);
    $rowT=$endtime->fetch_row();
    $updatedEndTime=$rowT[0] . ":00:00";
  $sql="update visits set endTime='" .$updatedEndTime . "' where id=" . $row[0] . ";";

  //echo $sql;

  $mysqli->query($sql);

}

 ?>
