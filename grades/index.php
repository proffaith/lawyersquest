<?php
include("index.html");

if($_SERVER["REQUEST_METHOD"] == "GET") {

  if($_GET['nav']==0) {

    require("list.php");

  }


}

if($_SERVER["REQUEST_METHOD"] == "POST") {
  $conn = mysqli_connect('localhost','GradesCheck','44C#atlantic','OERAnalysis');

  // Check the connection
  if (!$conn) {
      die("Connection failed: " . mysqli_connect_error());
  }

    if($_POST['nav']==10) {

        // Handle form submission
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            $dataID = $_POST["dataID"];
            $age = $_POST["Age"];
            $gender = $_POST["gender"];
            $race = $_POST["race"];
            $credits = $_POST["credits"];
            $gpa = $_POST["gpa"];

            $sqlUpdate="UPDATE mngt140data SET ";
            if(isset($age) and $age!="") { $sqlUpdate.="Age=$age,"; }
            if(isset($gender) and $gender!="") { $sqlUpdate.="isMaleT1=$gender,"; }
            if(isset($race) and $race!="") { $sqlUpdate.="isWhiteAsianT1=$race,"; }
            if(isset($credits) and $credits!="") { $sqlUpdate.="OverallHoursAttempted=$credits,"; }
            if(isset($gpa) and $gpa!="") { $sqlUpdate.="OverallGPA=$gpa,"; }
            $sqlUpdate.="JournalAverage=0";

            // Construct the SQL query to update the record
            $sqlUpdate.= " WHERE dataid=$dataID";
            //echo $sqlUpdate;

            if (mysqli_query($conn, $sqlUpdate)) {
                echo "Record #".$dataID." updated successfully.";
            } else {

                echo "Error updating record: " . mysqli_error($conn);
            }
        }
        require("list.php");
      }

}

?>
